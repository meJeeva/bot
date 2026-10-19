"""Market-data REST endpoints.

``GET /api/market/quote``      - latest XAUUSD bid / ask / spread / freshness
``GET /api/market/candles``    - historical OHLC for one of the seven timeframes
``GET /api/market/snapshot``   - connection + symbol + quote + update time
``GET /api/market/symbols``    - symbol discovery detail (ambiguity diagnostics)
``GET /api/market/timeframes`` - the supported timeframe list
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ..config import Settings
from ..errors import ApiError
from ..mt5.connection import MT5UnavailableError
from ..mt5.market_data import MarketDataError
from ..mt5.timeframes import (
    SUPPORTED_TIMEFRAMES,
    TIMEFRAMES,
    UnsupportedTimeframeError,
    normalize_timeframe,
)
from ..schemas.market import CandleSeries, MarketSnapshot, Quote
from ..services.market_monitor import MarketMonitor
from .deps import get_monitor, get_settings

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/quote", response_model=Quote, summary="Latest tick for the symbol")
async def quote(monitor: MarketMonitor = Depends(get_monitor)) -> Quote:
    """Return the most recent usable tick.

    Answers ``503`` when no tick has been received yet. Prices that the
    terminal could not supply are returned as ``null`` - never as ``0``.
    """
    latest = monitor.latest_quote()
    if latest is None:
        raise ApiError(
            "quote_unavailable",
            monitor.last_error
            or "No executable tick has been received from MetaTrader 5 yet.",
            status_code=503,
            detail={"symbol": monitor.settings.mt5_symbol},
        )
    return latest


@router.get("/candles", response_model=CandleSeries, summary="Historical candles")
async def candles(
    timeframe: str = Query(default="M15", description="One of M1, M5, M15, M30, H1, H4, D1"),
    limit: int = Query(default=300, description="Number of bars to return"),
    monitor: MarketMonitor = Depends(get_monitor),
    settings: Settings = Depends(get_settings),
) -> CandleSeries:
    """Return OHLC history for one of the seven supported timeframes."""
    try:
        name = normalize_timeframe(timeframe)
    except UnsupportedTimeframeError as exc:
        raise ApiError(
            "unsupported_timeframe",
            str(exc),
            status_code=400,
            detail={"supported": list(SUPPORTED_TIMEFRAMES)},
        ) from exc

    if limit < 1:
        raise ApiError(
            "invalid_limit",
            f"limit must be at least 1, received {limit}.",
            status_code=400,
            detail={"min": 1, "max": settings.max_candle_limit},
        )
    if limit > settings.max_candle_limit:
        raise ApiError(
            "invalid_limit",
            f"limit must not exceed MAX_CANDLE_LIMIT "
            f"({settings.max_candle_limit}), received {limit}.",
            status_code=400,
            detail={"min": 1, "max": settings.max_candle_limit},
        )

    try:
        return await monitor.get_candles(name, limit)
    except MarketDataError as exc:
        raise ApiError(
            exc.code,
            exc.message,
            status_code=503,
            detail={"timeframe": name, "symbol": monitor.settings.mt5_symbol},
        ) from exc
    except MT5UnavailableError as exc:
        raise ApiError("mt5_unavailable", str(exc), status_code=503) from exc


@router.get("/snapshot", response_model=MarketSnapshot, summary="Combined snapshot")
async def snapshot(monitor: MarketMonitor = Depends(get_monitor)) -> MarketSnapshot:
    """Connection status, symbol, latest quote and the latest update time."""
    return await monitor.build_snapshot()


@router.get("/timeframes", summary="Supported timeframes")
async def timeframes() -> dict[str, Any]:
    """List the seven supported timeframes with their MT5 constants."""
    return {
        "supported": [
            {
                "name": name,
                "label": TIMEFRAMES[name].label,
                "seconds": TIMEFRAMES[name].seconds,
                "mt5_value": TIMEFRAMES[name].mt5_value,
            }
            for name in SUPPORTED_TIMEFRAMES
        ]
    }


@router.get("/symbols", summary="Symbol discovery detail")
async def symbols(monitor: MarketMonitor = Depends(get_monitor)) -> dict[str, Any]:
    """Report how the trading symbol was resolved.

    When the resolution is ``ambiguous`` this lists the candidates so an
    operator can pin ``MT5_SYMBOL`` explicitly instead of the bot guessing.
    """
    status = monitor.symbol_status
    return {
        "requested": status.requested,
        "resolved": status.resolved,
        "resolution": status.resolution,
        "matched_by": status.matched_by,
        "modifier": status.modifier,
        "requires_configuration": status.requires_configuration,
        "candidates": status.candidates,
        "message": status.message,
        "info": status.info.model_dump() if status.info else None,
    }
