"""``WS /ws/market`` - live market-data stream for the dashboard.

Behaviour
---------
* Sends a full snapshot immediately after the client connects.
* Sends a new snapshot whenever market data actually changes (or at least once
  per ``WS_PUSH_INTERVAL_MS``).
* Supports many simultaneous dashboard clients - each gets its own bounded
  queue, and a slow client has its oldest frame dropped rather than growing
  memory without limit.
* Sends a heartbeat frame so an idle connection is still proven alive and a
  vanished client is detected.
* Keeps streaming after an MT5 disconnect by reporting ``stale`` /
  ``unavailable`` state, and recovers automatically when the terminal returns.
"""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder

from ..logging_config import get_logger
from ..schemas.market import WsStatusMessage
from .deps import monitor_from_websocket

logger = get_logger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/market")
async def market_stream(websocket: WebSocket) -> None:
    """Stream market-data snapshots to a dashboard client."""
    try:
        monitor = monitor_from_websocket(websocket)
    except Exception as exc:  # pragma: no cover - defensive
        await websocket.close(code=1011, reason=str(exc))
        return

    await websocket.accept()
    queue = monitor.subscribe()
    client = f"{websocket.client.host}:{websocket.client.port}" if websocket.client else "?"
    logger.info("WebSocket client connected: %s", client)

    heartbeat = monitor.settings.ws_heartbeat_seconds

    try:
        # 1. Initial snapshot so the dashboard renders immediately.
        initial = await monitor.build_snapshot()
        await websocket.send_json(jsonable_encoder(initial))

        # 2. Continuous updates.
        while True:
            try:
                snapshot = await asyncio.wait_for(queue.get(), timeout=heartbeat)
            except asyncio.TimeoutError:
                frame = WsStatusMessage(
                    type="heartbeat",
                    message="stream alive",
                )
                await websocket.send_json(jsonable_encoder(frame))
                continue

            await websocket.send_json(jsonable_encoder(snapshot))

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected: %s", client)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - never crash the server
        logger.warning("WebSocket error for %s: %s", client, exc)
        with contextlib.suppress(Exception):
            await websocket.send_json(
                jsonable_encoder(
                    WsStatusMessage(
                        type="error",
                        code="stream_error",
                        message="The market-data stream hit an internal error.",
                    )
                )
            )
    finally:
        monitor.unsubscribe(queue)
        with contextlib.suppress(Exception):
            await websocket.close()
        logger.info("WebSocket client closed: %s", client)
