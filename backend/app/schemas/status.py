"""Response schemas for health, MT5 connection status and error payloads."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    """Timezone-aware current UTC time."""
    return datetime.now(timezone.utc)


class ConnectionState(str, Enum):
    """Coarse connection state shown on the dashboard."""

    CONNECTED = "connected"
    CONNECTING = "connecting"
    RECONNECTING = "reconnecting"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class DataStatus(str, Enum):
    """Freshness of the market data currently held by the backend."""

    LIVE = "live"
    STALE = "stale"
    UNAVAILABLE = "unavailable"

    @staticmethod
    def from_freshness(is_stale: bool | None, available: bool) -> "DataStatus":
        if not available:
            return DataStatus.UNAVAILABLE
        return DataStatus.STALE if is_stale else DataStatus.LIVE


class AccountType(str, Enum):
    """Demo/live classification when it can be established reliably."""

    DEMO = "demo"
    LIVE = "live"
    UNKNOWN = "unknown"


class SymbolInfo(BaseModel):
    """Broker-provided contract specification."""

    model_config = ConfigDict(extra="forbid")

    name: str
    digits: int = Field(ge=0, le=12)
    point: float = Field(gt=0)
    tick_size: float | None = Field(default=None, gt=0)
    tick_value: float | None = Field(default=None, ge=0)
    broker_spread_points: int | None = None
    currency_base: str | None = None
    currency_profit: str | None = None


class SymbolStatus(BaseModel):
    """How the trading symbol was resolved on this terminal."""

    requested: str
    resolved: str | None = None
    resolution: Literal["resolved", "ambiguous", "not_found", "unavailable", "pending"] = (
        "pending"
    )
    matched_by: str | None = None
    modifier: str | None = None
    message: str = ""
    candidates: list[str] = Field(default_factory=list)
    requires_configuration: bool = False
    info: SymbolInfo | None = None


class MT5Status(BaseModel):
    """Safe, loggable MT5 connection status.

    Never contains a password, token or (by default) a full account login.
    """

    state: ConnectionState = ConnectionState.DISCONNECTED
    mt5_initialized: bool = False
    terminal_connected: bool = False

    terminal_path: str | None = None
    terminal_name: str | None = None
    terminal_company: str | None = None
    terminal_build: int | None = None
    terminal_language: str | None = None

    trading_server: str | None = None

    account_login_masked: str | None = None
    account_login: int | None = None
    account_currency: str | None = None
    account_type: AccountType = AccountType.UNKNOWN
    account_trade_mode: int | None = None

    last_connected_at: datetime | None = None
    last_connection_error: str | None = None
    last_market_data_at: datetime | None = None

    reconnecting: bool = False
    reconnect_attempts: int = 0
    next_reconnect_at: datetime | None = None

    server_time_offset_seconds: int | None = None
    time_convention: str = (
        "Broker (server) local time. UTC values are derived by subtracting "
        "server_time_offset_seconds; the offset is measured, not assumed."
    )

    trading_enabled: bool = False
    read_only: bool = True

    timestamp: datetime = Field(default_factory=utc_now)


class MT5StatusResponse(BaseModel):
    """``GET /api/mt5/status`` payload."""

    status: MT5Status
    symbol: SymbolStatus


class HealthResponse(BaseModel):
    """``GET /api/health`` payload."""

    status: Literal["ok", "degraded"] = "ok"
    app_name: str
    version: str
    environment: str
    started_at: datetime
    uptime_seconds: float = Field(ge=0)
    read_only: bool = True
    trading_enabled: bool = False
    mt5_initialized: bool = False
    terminal_connected: bool = False
    data_status: DataStatus = DataStatus.UNAVAILABLE
    timestamp: datetime = Field(default_factory=utc_now)


class ErrorBody(BaseModel):
    """Machine-readable error payload used by every failure response."""

    code: str
    message: str
    detail: Any | None = None
