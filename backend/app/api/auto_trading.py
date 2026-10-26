"""Automatic trading REST endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..schemas.auto_trading import AutoTradingHistoryResponse, AutoTradingStatus
from .deps import get_auto_trading_controller, get_store

router = APIRouter(prefix="/api/auto-trading", tags=["auto-trading"])


@router.post("/start", response_model=AutoTradingStatus, summary="Start automatic trading")
async def start(controller=Depends(get_auto_trading_controller)) -> AutoTradingStatus:
    return await controller.start()


@router.post("/stop", response_model=AutoTradingStatus, summary="Stop automatic trading")
async def stop(controller=Depends(get_auto_trading_controller)) -> AutoTradingStatus:
    return await controller.stop()


@router.get("/status", response_model=AutoTradingStatus, summary="Automatic trading status")
async def status(controller=Depends(get_auto_trading_controller)) -> AutoTradingStatus:
    return await controller.status()


@router.get("/history", response_model=AutoTradingHistoryResponse, summary="Automatic trading history")
async def history(controller=Depends(get_auto_trading_controller)) -> AutoTradingHistoryResponse:
    return await controller.history()


@router.get("/trade-history", summary="Persisted individual trade history")
async def trade_history(
    store=Depends(get_store),
    limit: int = 100,
    offset: int = 0,
    symbol: str | None = None,
    direction: str | None = None,
    cycle_id: str | None = None,
    exit_reason: str | None = None,
    status: str | None = None,
    start: str | None = None,
    end: str | None = None,
):
    if store is None:
        return {"items": [], "count": 0}
    items = store.recent_trades(
        limit=limit,
        offset=offset,
        symbol=symbol,
        direction=direction,
        cycle_id=cycle_id,
        exit_reason=exit_reason,
        status=status,
        start=start,
        end=end,
    )
    return {"items": items, "count": len(items)}


@router.get("/trade-events", summary="Persisted trade execution events")
async def trade_events(store=Depends(get_store), limit: int = 200):
    if store is None:
        return {"items": [], "count": 0}
    items = store.recent_trade_events(limit)
    return {"items": items, "count": len(items)}
