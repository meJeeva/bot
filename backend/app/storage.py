"""Minimal SQLite persistence for status and market-data telemetry.

The store keeps a durable record of when the MT5 connection changed state and
what the market data looked like, so the dashboard can show recent connection
errors after a backend restart.

The store is deliberately small, synchronous and failure-tolerant: a database
problem must never take down the market-data monitor. Callers wrap the blocking
methods with :func:`asyncio.to_thread`.
"""

from __future__ import annotations

import json
import sqlite3
import threading
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

CREATE TABLE IF NOT EXISTS auto_trading_state (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    state_json  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
"""


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

    def save_auto_trading_state(self, state: dict[str, Any]) -> bool:
        """Persist the latest auto-trading state snapshot (single row)."""
        if not isinstance(state, dict):
            return False
        payload = json.dumps(state, default=str)
        now = datetime.now(timezone.utc).isoformat()
        cursor = self._execute(
            """
            INSERT INTO auto_trading_state (id, state_json, updated_at)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                state_json = excluded.state_json,
                updated_at = excluded.updated_at
            """,
            (payload, now),
        )
        return cursor is not None

    def load_auto_trading_state(self) -> dict[str, Any] | None:
        with self._lock:
            if self._connection is None:
                return None
            try:
                row = self._connection.execute(
                    "SELECT state_json FROM auto_trading_state WHERE id = 1"
                ).fetchone()
            except sqlite3.Error as exc:  # pragma: no cover - defensive
                self._last_error = str(exc)
                logger.warning("SQLite read failed: %s", exc)
                return None
        if not row or not row[0]:
            return None
        try:
            value = json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return None
        return value if isinstance(value, dict) else None

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
