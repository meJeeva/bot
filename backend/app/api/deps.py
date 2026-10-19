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


def require_store(request: Request) -> StatusStore:
    """Return the store, raising a clean 503 when persistence is unavailable."""
    store = getattr(request.app.state, "store", None)
    if store is None or not store.enabled:
        raise ApiError(
            "persist_unavailable",
            "Persistence is not available.",
            status_code=503,
        )
    return store


def monitor_from_websocket(websocket: WebSocket) -> MarketMonitor:
    monitor = getattr(websocket.app.state, "monitor", None)
    if monitor is None:
        raise ApiError(
            "monitor_unavailable",
            "The market-data monitor is not running.",
            status_code=503,
        )
    return monitor


def get_execution_authorizer(request: Request):
    """Return the shared Phase 4 execution authorization, or a clean 503 when absent."""
    from ..execution import ExecutionAuthorization

    auth = getattr(request.app.state, "execution_authorization", None)
    if auth is None:
        raise ApiError(
            "execution_unavailable",
            "The execution authorization is not running.",
            status_code=503,
        )
    return auth


def get_execution_adapter(request: Request):
    """Return the shared Phase 4 execution adapter, or a clean 503 when absent."""
    from ..execution import Mt5ExecutionAdapter

    adapter = getattr(request.app.state, "execution_adapter", None)
    if adapter is None:
        raise ApiError(
            "execution_unavailable",
            "The execution adapter is not running.",
            status_code=503,
        )
    return adapter
