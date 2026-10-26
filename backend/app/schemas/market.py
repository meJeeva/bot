"""Response schemas for quotes, candles and combined snapshots.

Timestamps
----------
MetaTrader 5 returns bar and tick times as "seconds since epoch" in the
**broker server's local time**, not UTC. Two fields are therefore always
published:

* the raw MetaTrader value (``time`` on :class:`Candle`), untouched, and
* ``open_time_utc`` / ``tick_time_utc`` - the UTC-corrected instant.

The correction is derived from a *measured* offset
(``server_time_offset_seconds``); nothing is assumed. See
:mod:`app.mt5.market_data`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .status import DataStatus, MT5Status, SymbolInfo, SymbolStatus, utc_now


class Quote(BaseModel):
    """Latest tick for the selected symbol.

    Unavailable values are ``None`` - never ``0`` and never a fabricated
    replacement price.
    """

    model_config = ConfigDict(extra="forbid")

    symbol: str
    bid: float | None = None
    ask: float | None = None
    last: float | None = None

    spread_price: float | None = None
    spread_points: float | None = None

    point: float = Field(gt=0)
    digits: int = Field(ge=0, le=12)
    tick_size: float | None = Field(default=None, gt=0)
    tick_value: float | None = Field(default=None, ge=0)

    tick_time_broker: datetime | None = None
    tick_time_utc: datetime | None = None
    age_seconds: float | None = Field(default=None, ge=0)

    freshness: Literal["live", "stale", "unknown"] = "unknown"
    is_stale: bool = False

    received_at: datetime = Field(default_factory=utc_now)
    server_time_offset_seconds: int | None = None

    @model_validator(mode="after")
    def _check_spread(self) -> "Quote":
        if self.bid is not None and self.ask is not None:
            expected = float(Decimal(str(self.ask)) - Decimal(str(self.bid)))
            if self.spread_price is not None and abs(self.spread_price - expected) > 1e-9:
                raise ValueError(
                    "spread_price must equal ask - bid "
                    f"({expected} != {self.spread_price})"
                )
            if self.spread_price is None:
                self.spread_price = expected
        return self


class Candle(BaseModel):
    """One OHLC bar.

    ``is_closed`` distinguishes the latest *completed* bar from the bar that is
    still forming. A forming bar must never be treated as complete.
    """

    model_config = ConfigDict(extra="forbid")

    # Raw MetaTrader value (broker-server seconds since epoch).
    time: int
    # Broker-local wall clock for the bar open.
    open_time_broker: datetime
    # UTC-corrected instant for the bar open.
    open_time_utc: datetime

    open: float
    high: float
    low: float
    close: float

    tick_volume: int = Field(default=0, ge=0)
    spread_points: int | None = None
    real_volume: int | None = Field(default=None, ge=0)

    is_closed: bool = True

    @model_validator(mode="after")
    def _check_ohlc(self) -> "Candle":
        if self.high < self.low:
            raise ValueError(f"invalid OHLC: high ({self.high}) < low ({self.low})")

        upper = max(self.open, self.close, self.high)
        lower = min(self.open, self.close, self.low)
        if self.high < upper - 1e-9:
            raise ValueError(
                f"invalid OHLC: high ({self.high}) below open/close ({upper})"
            )
        if self.low > lower + 1e-9:
            raise ValueError(
                f"invalid OHLC: low ({self.low}) above open/close ({lower})"
            )
        return self


class TimeframeSummary(BaseModel):
    """Compact per-timeframe summary used in the WebSocket snapshot."""

    timeframe: str
    seconds: int = Field(gt=0)
    latest_closed: Candle | None = None
    forming: Candle | None = None
    candle_count: int = Field(default=0, ge=0)
    last_updated: datetime | None = None
    error: str | None = None


class CandleSeries(BaseModel):
    """``GET /api/market/candles`` payload."""

    symbol: str
    timeframe: str
    timeframe_seconds: int = Field(gt=0)
    requested_limit: int = Field(gt=0)
    count: int = Field(ge=0)

    candles: list[Candle] = Field(default_factory=list)
    latest_candle: Candle | None = None
    latest_closed_candle: Candle | None = None

    server_time_offset_seconds: int | None = None
    time_convention: str = "broker_server_local"
    incomplete_history: bool = False
    warnings: list[str] = Field(default_factory=list)

    generated_at: datetime = Field(default_factory=utc_now)


class MarketSnapshot(BaseModel):
    """Combined payload streamed over ``WS /ws/market``."""

    type: Literal["snapshot"] = "snapshot"
    sequence: int = Field(ge=0)
    generated_at: datetime = Field(default_factory=utc_now)

    connection: MT5Status
    symbol: SymbolStatus
    quote: Quote | None = None

    data_status: DataStatus = DataStatus.UNAVAILABLE
    last_market_update: datetime | None = None
    quote_age_seconds: float | None = Field(default=None, ge=0)

    timeframes: dict[str, TimeframeSummary] = Field(default_factory=dict)
    last_error: str | None = None
    trading_enabled: bool = False
    read_only: bool = True


class WsStatusMessage(BaseModel):
    """Non-snapshot control frames sent over the WebSocket."""

    type: Literal["status", "error", "heartbeat"]
    message: str
    code: str | None = None
    timestamp: datetime = Field(default_factory=utc_now)
