"""Minimal SQLite persistence for status, market-data telemetry and execution records.

The store keeps a durable record of when the MT5 connection changed state and
what the market data looked like, so the dashboard can show recent connection
errors after a backend restart, plus the durable demo-execution and risk-state
records required by the execution subsystem.

The store is deliberately small, synchronous and failure-tolerant: a database
problem must never take down the market-data monitor. Callers wrap the blocking
methods with :func:`asyncio.to_thread`.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .logging_config import get_logger
from .schemas.market import Quote
from .schemas.status import MT5Status

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS connection_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    state           TEXT    NOT NULL,
    initialized     INTEGER NOT NULL,
    connected       INTEGER NOT NULL,
    account_type    TEXT,
    symbol          TEXT,
    error           TEXT
);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    bid             REAL,
    ask             REAL,
    spread_points   REAL,
    freshness       TEXT    NOT NULL,
    age_seconds     REAL,
    received_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_connection_events_timestamp
    ON connection_events (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_market_snapshots_timestamp
    ON market_snapshots (timestamp DESC);

-- Phase 4: durable demo-execution records. The unique idempotency key is the
-- database-level backstop against duplicate orders for one strategy setup.
-- Account identity is stored masked only; no secrets ever reach this table.
CREATE TABLE IF NOT EXISTS executions (
    id                      TEXT    PRIMARY KEY,
    idempotency_key         TEXT    NOT NULL UNIQUE,
    setup_id                TEXT    NOT NULL,
    symbol                  TEXT    NOT NULL,
    timeframe               TEXT    NOT NULL,
    direction               TEXT    NOT NULL,
    source                  TEXT    NOT NULL DEFAULT 'live_strategy',
    signal_time_utc         TEXT,
    confirmation_time_utc   TEXT,
    config_fingerprint      TEXT,
    account_login_masked    TEXT,
    account_server          TEXT,
    requested_volume        REAL,
    actual_volume           REAL,
    entry_price             REAL,
    stop_loss               REAL,
    take_profit             REAL,
    risk_budget             REAL,
    estimated_loss          REAL,
    assessment_json         TEXT,
    state                   TEXT    NOT NULL,
    stage                   TEXT,
    broker_retcode          INTEGER,
    broker_order_id         INTEGER,
    broker_deal_id          INTEGER,
    position_id             INTEGER,
    fill_price              REAL,
    error_code              TEXT,
    error_message           TEXT,
    reconciliation          TEXT,
    created_at              TEXT    NOT NULL,
    updated_at              TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_executions_idempotency
    ON executions (idempotency_key);
CREATE INDEX IF NOT EXISTS idx_executions_created
    ON executions (created_at DESC);

-- Phase 4: persistent risk state. Daily baselines and lockouts must survive
-- restarts; losing them would reset protections.
CREATE TABLE IF NOT EXISTS execution_risk_state (
    key                     TEXT    PRIMARY KEY,
    risk_date               TEXT,
    baseline_equity         REAL,
    baseline_balance        REAL,
    high_water_equity       REAL,
    lockout_reason          TEXT,
    lockout_at              TEXT,
    consecutive_losses      INTEGER,
    last_reconciled_at      TEXT,
    updated_at              TEXT    NOT NULL
);
"""


@dataclass
class StoreStats:
    """Cheap diagnostics for the status endpoint."""

    enabled: bool
    path: str | None
    connection_events: int = 0
    market_snapshots: int = 0
    last_error: str | None = None


class StoreWriteError(RuntimeError):
    """A required durable write failed (Phase 4 execution must fail closed)."""


class StoreConflictError(StoreWriteError):
    """A uniqueness constraint refused the write (duplicate idempotency key)."""


class StatusStore:
    """Thread-safe SQLite store for connection events and market snapshots."""

    def __init__(self, path: Path, *, enabled: bool = True) -> None:
        self._path = Path(path)
        self._enabled = enabled
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None
        self._last_error: str | None = None
        self._failures = 0
        self._last_event_key: tuple[Any, ...] | None = None

    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self._enabled and self._connection is not None

    @property
    def path(self) -> Path:
        return self._path

    def initialize(self) -> bool:
        """Open the database and create the schema. Never raises."""
        if not self._enabled:
            logger.info("SQLite persistence is disabled by configuration.")
            return False

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(
                str(self._path), check_same_thread=False, timeout=10.0
            )
            connection.execute("PRAGMA journal_mode=WAL;")
            connection.executescript(_SCHEMA)
            connection.commit()
            with self._lock:
                self._connection = connection
            logger.info("SQLite status store ready at %s", self._path)
            return True
        except sqlite3.Error as exc:
            self._last_error = str(exc)
            self._enabled = False
            logger.warning(
                "SQLite status store could not be initialized (%s). Continuing "
                "without persistence.",
                exc,
            )
            return False

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                try:
                    self._connection.close()
                except sqlite3.Error:  # pragma: no cover - defensive
                    pass
                self._connection = None
        logger.debug("SQLite status store closed.")

    # ------------------------------------------------------------------
    def _execute(self, sql: str, params: tuple[Any, ...]) -> sqlite3.Cursor | None:
        with self._lock:
            if self._connection is None:
                return None
            try:
                cursor = self._connection.execute(sql, params)
                self._connection.commit()
                self._failures = 0
                return cursor
            except sqlite3.Error as exc:
                self._failures += 1
                self._last_error = str(exc)
                logger.warning("SQLite write failed (%s): %s", self._failures, exc)
                if self._failures >= 5:
                    logger.error(
                        "Disabling SQLite persistence after %s consecutive failures.",
                        self._failures,
                    )
                    self._enabled = False
                return None

    def record_connection_event(
        self, status: MT5Status, *, symbol: str | None = None
    ) -> bool:
        """Persist a connection-state transition (deduplicated)."""
        key = (
            status.state.value,
            status.mt5_initialized,
            status.terminal_connected,
            status.account_type.value,
            status.last_connection_error,
        )
        if key == self._last_event_key:
            return False

        cursor = self._execute(
            """
            INSERT INTO connection_events
                (timestamp, state, initialized, connected, account_type, symbol, error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                status.state.value,
                int(status.mt5_initialized),
                int(status.terminal_connected),
                status.account_type.value,
                symbol,
                status.last_connection_error,
            ),
        )
        if cursor is not None:
            self._last_event_key = key
            return True
        return False

    def record_quote(self, quote: Quote) -> bool:
        """Persist the latest tick snapshot."""
        cursor = self._execute(
            """
            INSERT INTO market_snapshots
                (timestamp, symbol, bid, ask, spread_points, freshness, age_seconds, received_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                quote.symbol,
                quote.bid,
                quote.ask,
                quote.spread_points,
                quote.freshness,
                quote.age_seconds,
                quote.received_at.isoformat() if quote.received_at else None,
            ),
        )
        return cursor is not None

    # ------------------------------------------------------------------
    def recent_connection_events(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            if self._connection is None:
                return []
            try:
                rows = self._connection.execute(
                    """
                    SELECT timestamp, state, initialized, connected, account_type, symbol, error
                    FROM connection_events
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (int(limit),),
                ).fetchall()
            except sqlite3.Error as exc:  # pragma: no cover - defensive
                logger.warning("SQLite read failed: %s", exc)
                return []

        return [
            {
                "timestamp": row[0],
                "state": row[1],
                "initialized": bool(row[2]),
                "connected": bool(row[3]),
                "account_type": row[4],
                "symbol": row[5],
                "error": row[6],
            }
            for row in rows
        ]

    def recent_errors(self, limit: int = 10) -> list[dict[str, Any]]:
        """Most recent connection events that carried an error message."""
        return [
            event
            for event in self.recent_connection_events(limit * 5)
            if event.get("error")
        ][:limit]

    def counts(self) -> tuple[int, int]:
        with self._lock:
            if self._connection is None:
                return (0, 0)
            try:
                events = self._connection.execute(
                    "SELECT COUNT(*) FROM connection_events"
                ).fetchone()[0]
                snapshots = self._connection.execute(
                    "SELECT COUNT(*) FROM market_snapshots"
                ).fetchone()[0]
            except sqlite3.Error:  # pragma: no cover - defensive
                return (0, 0)
        return (int(events), int(snapshots))

    def stats(self) -> StoreStats:
        events, snapshots = self.counts()
        return StoreStats(
            enabled=self.enabled,
            path=str(self._path) if self._enabled else None,
            connection_events=events,
            market_snapshots=snapshots,
            last_error=self._last_error,
        )

    # ==================================================================
    # Phase 4: execution records and risk state (strict writes)
    #
    # Unlike the telemetry writers above - which are deliberately
    # failure-tolerant so a database hiccup never stops market monitoring -
    # these methods RAISE when the durable record cannot be written. Execution
    # treats "cannot persist" as "cannot trade" (fail closed).
    # ==================================================================
    _EXECUTION_COLUMNS = (
        "id", "idempotency_key", "setup_id", "symbol", "timeframe", "direction",
        "source", "signal_time_utc", "confirmation_time_utc", "config_fingerprint",
        "account_login_masked", "account_server", "requested_volume", "actual_volume",
        "entry_price", "stop_loss", "take_profit", "risk_budget", "estimated_loss",
        "assessment_json", "state", "stage", "broker_retcode", "broker_order_id",
        "broker_deal_id", "position_id", "fill_price", "error_code", "error_message",
        "reconciliation", "created_at", "updated_at",
    )

    _RISK_STATE_COLUMNS = (
        "key", "risk_date", "baseline_equity", "baseline_balance",
        "high_water_equity", "lockout_reason", "lockout_at",
        "consecutive_losses", "last_reconciled_at", "updated_at",
    )

    def _execute_strict(self, sql: str, params: tuple[Any, ...]) -> sqlite3.Cursor:
        """Execute a required write; raise instead of swallowing failures."""
        with self._lock:
            if self._connection is None:
                raise StoreWriteError(
                    "Execution persistence is unavailable (database not open)."
                )
            try:
                cursor = self._connection.execute(sql, params)
                self._connection.commit()
                self._failures = 0
                return cursor
            except sqlite3.IntegrityError as exc:
                raise StoreConflictError(str(exc)) from exc
            except sqlite3.Error as exc:
                self._failures += 1
                self._last_error = str(exc)
                logger.error("Execution write failed: %s", exc)
                raise StoreWriteError(str(exc)) from exc

    def record_execution(self, row: dict[str, Any]) -> None:
        """Persist a new execution record (idempotency key must be unique)."""
        columns = self._EXECUTION_COLUMNS
        missing = [c for c in columns if c not in row]
        if missing:
            raise StoreWriteError(f"Execution row is missing columns: {missing}")
        placeholders = ", ".join("?" for _ in columns)
        self._execute_strict(
            f"INSERT INTO executions ({', '.join(columns)}) VALUES ({placeholders})",
            tuple(row[c] for c in columns),
        )

    def update_execution(self, execution_id: str, updates: dict[str, Any]) -> None:
        """Update an existing execution record; unknown ids raise."""
        if not updates:
            return
        unknown = [c for c in updates if c not in self._EXECUTION_COLUMNS]
        if unknown:
            raise StoreWriteError(f"Unknown execution columns: {unknown}")
        assignments = ", ".join(f"{c} = ?" for c in updates)
        cursor = self._execute_strict(
            f"UPDATE executions SET {assignments} WHERE id = ?",
            (*tuple(updates[c] for c in updates), execution_id),
        )
        if cursor.rowcount == 0:
            raise StoreWriteError(
                f"Execution {execution_id!r} does not exist; refusing to pretend "
                "a record was updated."
            )

    def _read_execution_rows(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self._lock:
            if self._connection is None:
                return []
            try:
                rows = self._connection.execute(sql, params).fetchall()
            except sqlite3.Error as exc:
                logger.warning("Execution read failed: %s", exc)
                return []
        return [dict(zip(self._EXECUTION_COLUMNS, row)) for row in rows]

    def get_execution(self, execution_id: str) -> dict[str, Any] | None:
        rows = self._read_execution_rows(
            f"SELECT {', '.join(self._EXECUTION_COLUMNS)} FROM executions WHERE id = ?",
            (execution_id,),
        )
        return rows[0] if rows else None

    def get_execution_by_key(self, idempotency_key: str) -> dict[str, Any] | None:
        rows = self._read_execution_rows(
            f"SELECT {', '.join(self._EXECUTION_COLUMNS)} FROM executions "
            "WHERE idempotency_key = ?",
            (idempotency_key,),
        )
        return rows[0] if rows else None

    def list_executions(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._read_execution_rows(
            f"SELECT {', '.join(self._EXECUTION_COLUMNS)} FROM executions "
            "ORDER BY created_at DESC LIMIT ?",
            (int(limit),),
        )

    def count_unresolved_executions(self) -> int:
        """Submissions whose outcome is not yet established (fail closed)."""
        with self._lock:
            if self._connection is None:
                return 0
            try:
                row = self._connection.execute(
                    "SELECT COUNT(*) FROM executions WHERE state IN "
                    "('submitting', 'unknown_outcome', 'reconciling')"
                ).fetchone()
            except sqlite3.Error as exc:  # pragma: no cover - defensive
                logger.warning("Unresolved-execution count failed: %s", exc)
                return 0
        return int(row[0]) if row else 0

    def get_execution_risk_state(self, key: str = "global") -> dict[str, Any] | None:
        with self._lock:
            if self._connection is None:
                return None
            try:
                row = self._connection.execute(
                    f"SELECT {', '.join(self._RISK_STATE_COLUMNS)} "
                    "FROM execution_risk_state WHERE key = ?",
                    (key,),
                ).fetchone()
            except sqlite3.Error as exc:
                logger.warning("Risk-state read failed: %s", exc)
                return None
        return dict(zip(self._RISK_STATE_COLUMNS, row)) if row else None

    def save_execution_risk_state(self, row: dict[str, Any]) -> None:
        """Persist the risk baseline/lockout row (INSERT OR REPLACE)."""
        columns = self._RISK_STATE_COLUMNS
        missing = [c for c in columns if c not in row]
        if missing:
            raise StoreWriteError(f"Risk-state row is missing columns: {missing}")
        placeholders = ", ".join("?" for _ in columns)
        self._execute_strict(
            f"INSERT OR REPLACE INTO execution_risk_state "
            f"({', '.join(columns)}) VALUES ({placeholders})",
            tuple(row[c] for c in columns),
        )

