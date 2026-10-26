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

CREATE TABLE IF NOT EXISTS trade_cycles (
    cycle_id        TEXT PRIMARY KEY,
    symbol          TEXT,
    profile         TEXT,
    reference_price REAL,
    status          TEXT,
    started_at      TEXT,
    completed_at    TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    trade_id                TEXT PRIMARY KEY,
    cycle_id                TEXT,
    previous_trade_id       TEXT,
    symbol                  TEXT,
    profile                 TEXT,
    direction               TEXT,
    order_ticket            INTEGER,
    position_id             INTEGER,
    entry_deal_id           INTEGER,
    exit_deal_id            INTEGER,
    status                  TEXT,
    entry_submitted_at      TEXT,
    entry_accepted_at       TEXT,
    entry_filled_at         TEXT,
    requested_entry_price   REAL,
    actual_entry_price      REAL,
    configured_lot_size     REAL,
    actual_volume           REAL,
    reference_price         REAL,
    initial_sl              REAL,
    confirmed_initial_sl    REAL,
    spread_at_entry         REAL,
    atr_at_entry            REAL,
    be_activation_distance  REAL,
    be_activation_threshold REAL,
    be_activated_at         TEXT,
    trail_distance          REAL,
    trail_cap               REAL,
    exit_requested_at       TEXT,
    exit_filled_at          TEXT,
    actual_exit_price       REAL,
    actual_exit_volume      REAL,
    exit_reason             TEXT,
    strategy_exit_class     TEXT,
    final_sl_before_exit    REAL,
    gross_profit            REAL,
    commission              REAL,
    swap                    REAL,
    net_profit              REAL,
    duration_seconds        REAL,
    mt5_result_code         INTEGER,
    request_latency_ms      REAL,
    created_at              TEXT,
    updated_at              TEXT,
    UNIQUE(order_ticket, position_id)
);

CREATE TABLE IF NOT EXISTS trade_events (
    event_id        TEXT PRIMARY KEY,
    cycle_id        TEXT,
    trade_id        TEXT,
    event_type      TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    broker_timestamp TEXT,
    price           REAL,
    order_ticket    INTEGER,
    position_id     INTEGER,
    result_code     INTEGER,
    details         TEXT
);

CREATE INDEX IF NOT EXISTS idx_trades_cycle ON trades(cycle_id);
CREATE INDEX IF NOT EXISTS idx_trade_events_cycle ON trade_events(cycle_id);
CREATE INDEX IF NOT EXISTS idx_trade_events_trade ON trade_events(trade_id);
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
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            row = connection.execute("SELECT MAX(version) FROM schema_version").fetchone()
            if row is None or row[0] is None:
                connection.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (1, ?)",
                    (datetime.now(timezone.utc).isoformat(),),
                )
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

    def record_trade(self, trade: dict[str, Any]) -> bool:
        if not isinstance(trade, dict):
            return False
        trade_id = trade.get("trade_id")
        if not trade_id:
            return False
        now = datetime.now(timezone.utc).isoformat()
        columns = [
            "trade_id", "cycle_id", "previous_trade_id", "symbol", "profile", "direction",
            "order_ticket", "position_id", "entry_deal_id", "exit_deal_id", "status",
            "entry_submitted_at", "entry_accepted_at", "entry_filled_at",
            "requested_entry_price", "actual_entry_price", "configured_lot_size", "actual_volume",
            "reference_price", "initial_sl", "confirmed_initial_sl", "spread_at_entry",
            "atr_at_entry", "be_activation_distance", "be_activation_threshold", "be_activated_at",
            "trail_distance", "trail_cap", "exit_requested_at", "exit_filled_at", "actual_exit_price",
            "actual_exit_volume", "exit_reason", "strategy_exit_class", "final_sl_before_exit",
            "gross_profit", "commission", "swap", "net_profit", "duration_seconds",
            "mt5_result_code", "request_latency_ms", "created_at", "updated_at",
        ]
        values = [trade.get(c) for c in columns[:-1]] + [now]
        # created_at handling
        if trade.get("created_at"):
            values[columns.index("created_at")] = trade.get("created_at")
        placeholders = ", ".join("?" for _ in columns)
        sql = f"INSERT INTO trades ({', '.join(columns)}) VALUES ({placeholders}) " \
              "ON CONFLICT(trade_id) DO UPDATE SET " + ", ".join(
                  f"{c}=excluded.{c}" for c in columns if c not in ("trade_id", "created_at")
              )
        cursor = self._execute(sql, tuple(values))
        return cursor is not None

    def upsert_trade(self, trade: dict[str, Any]) -> bool:
        return self.record_trade(trade)

    def record_trade_event(self, event: dict[str, Any]) -> bool:
        if not isinstance(event, dict):
            return False
        event_id = event.get("event_id")
        if not event_id:
            return False
        columns = [
            "event_id", "cycle_id", "trade_id", "event_type", "timestamp",
            "broker_timestamp", "price", "order_ticket", "position_id", "result_code", "details",
        ]
        values = [event.get(c) for c in columns]
        placeholders = ", ".join("?" for _ in columns)
        sql = f"INSERT INTO trade_events ({', '.join(columns)}) VALUES ({placeholders}) " \
              "ON CONFLICT(event_id) DO NOTHING"
        cursor = self._execute(sql, tuple(values))
        return cursor is not None

    def recent_trades(
        self,
        limit: int = 50,
        offset: int = 0,
        symbol: str | None = None,
        direction: str | None = None,
        cycle_id: str | None = None,
        exit_reason: str | None = None,
        status: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            if self._connection is None:
                return []
            try:
                clauses = []
                params: list[Any] = []
                if symbol:
                    clauses.append("symbol = ?")
                    params.append(symbol)
                if direction:
                    clauses.append("direction = ?")
                    params.append(direction.upper())
                if cycle_id:
                    clauses.append("cycle_id = ?")
                    params.append(cycle_id)
                if exit_reason:
                    clauses.append("exit_reason = ?")
                    params.append(exit_reason)
                if status:
                    clauses.append("status = ?")
                    params.append(status)
                if start:
                    clauses.append("created_at >= ?")
                    params.append(start)
                if end:
                    clauses.append("created_at <= ?")
                    params.append(end)
                where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
                sql = f"SELECT * FROM trades{where} ORDER BY rowid DESC LIMIT ? OFFSET ?"
                params.extend([int(limit), int(offset)])
                rows = self._connection.execute(sql, tuple(params)).fetchall()
                cols = [d[0] for d in self._connection.execute("SELECT * FROM trades LIMIT 1").description]
            except sqlite3.Error:
                return []
        return [dict(zip(cols, row)) for row in rows]

    def recent_trade_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            if self._connection is None:
                return []
            try:
                rows = self._connection.execute(
                    "SELECT * FROM trade_events ORDER BY rowid DESC LIMIT ?", (int(limit),)
                ).fetchall()
                cols = [d[0] for d in self._connection.execute("SELECT * FROM trade_events LIMIT 1").description]
            except sqlite3.Error:
                return []
        return [dict(zip(cols, row)) for row in rows]

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
