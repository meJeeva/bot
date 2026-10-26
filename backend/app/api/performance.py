"""Read-only trading-performance endpoints.

Every route here is a GET. Nothing in this module submits, modifies or closes
an order, and none of it touches the auto-trading worker or its reconciliation
state: the endpoints only read MT5 deal history, open positions and account
information through the shared serialised connection.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from ..schemas.performance import (
    DailyPerformanceResponse,
    PerformanceSummary,
    PerformanceTradesResponse,
)
from ..services.performance import PerformanceService
from .deps import get_performance_service

router = APIRouter(prefix="/api/performance", tags=["performance"])

DirectionFilter = Annotated[
    Literal["buy", "sell"] | None,
    Query(description="Filter trades by direction"),
]


def _service(
    preset: str | None,
    start: date | None,
    end: date | None,
    symbol: str | None,
    direction: str | None,
    magic: int | None,
) -> dict[str, object]:
    return {
        "preset": preset,
        "start": start,
        "end": end,
        "symbol": symbol,
        "direction": direction,
        "magic": magic,
    }


@router.get(
    "/summary",
    response_model=PerformanceSummary,
    summary="Realized and floating P&L for a reporting range",
)
async def performance_summary(
    service: Annotated[PerformanceService, Depends(get_performance_service)],
    preset: Annotated[str | None, Query(description="today|yesterday|d7|d30|week|month")] = None,
    start: Annotated[date | None, Query(description="Range start (YYYY-MM-DD, reporting timezone)")] = None,
    end: Annotated[date | None, Query(description="Range end, inclusive")] = None,
    symbol: Annotated[str | None, Query(description="Filter by symbol")] = None,
    direction: DirectionFilter = None,
    magic: Annotated[int | None, Query(description="Filter by magic number")] = None,
) -> PerformanceSummary:
    return await service.summary(**_service(preset, start, end, symbol, direction, magic))


@router.get(
    "/daily",
    response_model=DailyPerformanceResponse,
    summary="Day-by-day realized P&L for a reporting range",
)
async def performance_daily(
    service: Annotated[PerformanceService, Depends(get_performance_service)],
    preset: Annotated[str | None, Query(description="today|yesterday|d7|d30|week|month")] = None,
    start: Annotated[date | None, Query(description="Range start (YYYY-MM-DD, reporting timezone)")] = None,
    end: Annotated[date | None, Query(description="Range end, inclusive")] = None,
    symbol: Annotated[str | None, Query(description="Filter by symbol")] = None,
    direction: DirectionFilter = None,
    magic: Annotated[int | None, Query(description="Filter by magic number")] = None,
) -> DailyPerformanceResponse:
    return await service.daily(**_service(preset, start, end, symbol, direction, magic))


@router.get(
    "/trades",
    response_model=PerformanceTradesResponse,
    summary="Completed trades with their full deal lifecycle",
)
async def performance_trades(
    service: Annotated[PerformanceService, Depends(get_performance_service)],
    preset: Annotated[str | None, Query(description="today|yesterday|d7|d30|week|month")] = None,
    start: Annotated[date | None, Query(description="Range start (YYYY-MM-DD, reporting timezone)")] = None,
    end: Annotated[date | None, Query(description="Range end, inclusive")] = None,
    symbol: Annotated[str | None, Query(description="Filter by symbol")] = None,
    direction: DirectionFilter = None,
    magic: Annotated[int | None, Query(description="Filter by magic number")] = None,
) -> PerformanceTradesResponse:
    return await service.trades(**_service(preset, start, end, symbol, direction, magic))
