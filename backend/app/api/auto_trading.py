"""Automatic trading REST endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..schemas.auto_trading import AutoTradingHistoryResponse, AutoTradingStatus
from .deps import get_auto_trading_controller

router = APIRouter(prefix="/api/auto-trading", tags=["auto-trading"])


@router.post("/start", response_model=AutoTradingStatus, summary="Start automatic M1 trading")
async def start(controller=Depends(get_auto_trading_controller)) -> AutoTradingStatus:
    return await controller.start()


@router.post("/stop", response_model=AutoTradingStatus, summary="Stop automatic M1 trading")
async def stop(controller=Depends(get_auto_trading_controller)) -> AutoTradingStatus:
    return await controller.stop()


@router.get("/status", response_model=AutoTradingStatus, summary="Automatic trading status")
async def status(controller=Depends(get_auto_trading_controller)) -> AutoTradingStatus:
    return await controller.status()


@router.get("/history", response_model=AutoTradingHistoryResponse, summary="Automatic trading history")
async def history(controller=Depends(get_auto_trading_controller)) -> AutoTradingHistoryResponse:
    return await controller.history()
