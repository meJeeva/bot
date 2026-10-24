"""Shared FastAPI dependencies.

The connection, monitor and store live on ``app.state`` so that a single MT5
connection and a single monitoring loop are shared by every request and every
WebSocket client.
"""

from __future__ import annotations

from fastapi import Request, WebSocket

from ..config import Settings
from ..errors import ApiError
from ..services.market_monitor import MarketMonitor
from ..storage import StatusStore


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_monitor(request: Request) -> MarketMonitor:
    monitor = getattr(request.app.state, "monitor", None)
    if monitor is None:
        raise ApiError(
            "monitor_unavailable",
            "The market-data monitor is not running.",
            status_code=503,
        )
    return monitor


def get_store(request: Request) -> StatusStore | None:
    return getattr(request.app.state, "store", None)


def monitor_from_websocket(websocket: WebSocket) -> MarketMonitor:
    monitor = getattr(websocket.app.state, "monitor", None)
    if monitor is None:
        raise ApiError(
            "monitor_unavailable",
            "The market-data monitor is not running.",
            status_code=503,
        )
    return monitor

def get_auto_trading_controller(request: Request):
    controller = getattr(request.app.state, "auto_trading", None)
    if controller is None:
        from ..errors import ApiError
        raise ApiError(
            "auto_trading_unavailable",
            "The automatic trading controller is not available.",
            status_code=503,
        )
    return controller


def get_performance_service(request: Request):
    service = getattr(request.app.state, "performance", None)
    if service is None:
        raise ApiError(
            "performance_unavailable",
            "The performance reporting service is not available.",
            status_code=503,
        )
    return service
