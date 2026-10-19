"""``GET /api/mt5/status`` - safe MetaTrader 5 connection and symbol status."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query

from ..schemas.events import ConnectionEvent, ConnectionEventsResponse
from ..schemas.status import MT5StatusResponse
from ..services.market_monitor import MarketMonitor
from ..storage import StatusStore
from .deps import get_monitor, get_store

router = APIRouter(prefix="/api/mt5", tags=["mt5"])


def _to_event(row: dict) -> ConnectionEvent:
    return ConnectionEvent(
        timestamp=datetime.fromisoformat(str(row["timestamp"])),
        state=str(row.get("state", "unknown")),
        initialized=bool(row.get("initialized")),
        connected=bool(row.get("connected")),
        account_type=row.get("account_type"),
        symbol=row.get("symbol"),
        error=row.get("error"),
    )


@router.get(
    "/status",
    response_model=MT5StatusResponse,
    summary="MT5 terminal, account and symbol status",
)
async def mt5_status(monitor: MarketMonitor = Depends(get_monitor)) -> MT5StatusResponse:
    """Return the current terminal/account status and symbol resolution.

    Always answers ``200`` - a disconnected terminal is a *state*, not a
    transport error, and the dashboard needs to render it. Passwords, tokens
    and full account logins are never included; the login is masked unless
    ``EXPOSE_ACCOUNT_LOGIN=true`` is set explicitly.
    """
    status = await monitor.connection_status()
    return MT5StatusResponse(status=status, symbol=monitor.symbol_status)


@router.get(
    "/events",
    response_model=ConnectionEventsResponse,
    summary="Recent MT5 connection events and errors",
)
async def connection_events(
    limit: int = Query(default=10, ge=1, le=100),
    store: StatusStore | None = Depends(get_store),
) -> ConnectionEventsResponse:
    """Recent connection-state transitions, newest first.

    Backed by the local SQLite status store, so the dashboard still shows recent
    errors after the backend has been restarted. Returns ``enabled=false`` with
    empty lists when persistence is switched off.
    """
    if store is None or not store.enabled:
        return ConnectionEventsResponse(enabled=False)

    events, snapshots = store.counts()
    return ConnectionEventsResponse(
        enabled=True,
        total_events=events,
        total_snapshots=snapshots,
        events=[_to_event(row) for row in store.recent_connection_events(limit)],
        errors=[_to_event(row) for row in store.recent_errors(limit)],
    )
