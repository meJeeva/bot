"""``GET /api/health`` - backend liveness, version and uptime."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..schemas.status import HealthResponse, utc_now
from ..services.market_monitor import MarketMonitor
from .deps import get_monitor

router = APIRouter(tags=["health"])


@router.get(
    "/api/health",
    response_model=HealthResponse,
    summary="Backend health, version and uptime",
)
async def health(monitor: MarketMonitor = Depends(get_monitor)) -> HealthResponse:
    """Report backend health.

    ``status`` is ``degraded`` whenever live market data is not flowing, so a
    green indicator never appears while the terminal is silent.

    This handler only reads cached state - it never performs a blocking
    MetaTrader call, so it keeps answering even when the terminal is hung.
    """
    now = utc_now()
    connection = monitor.cached_connection_status()
    if connection is None:
        # Nothing is cached until the first poll completes, so read the
        # terminal once instead of reporting a misleading "disconnected".
        connection = await monitor.connection_status()
    data_status = monitor.data_status

    return HealthResponse(
        status="ok" if data_status.value == "live" else "degraded",
        app_name=monitor.settings.app_name,
        version=monitor.settings.app_version,
        environment=monitor.settings.app_env,
        started_at=monitor.started_at,
        uptime_seconds=max(0.0, (now - monitor.started_at).total_seconds()),
        read_only=True,
        trading_enabled=False,
        mt5_initialized=bool(connection and connection.mt5_initialized),
        terminal_connected=bool(connection and connection.terminal_connected),
        data_status=data_status,
        timestamp=now,
    )
