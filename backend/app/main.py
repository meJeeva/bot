"""FastAPI application factory and lifespan wiring.

One process owns one MT5 connection and one background market monitor; every
HTTP and WebSocket handler only reads that shared state.

This factory was rebuilt from the contracts that already exist in the
repository - the routers in :mod:`app.api`, the dependencies in
``app/api/deps.py``, the response schemas and the end-to-end tests. Behaviour
is deliberately unchanged:

* **Read-only.** No route places, modifies or closes an order. Execution stays
  behind the demo-only authorization object, which starts ``DISABLED`` and can
  only be armed by an explicit operator action after a successful demo-account
  verification.
* **Fail closed.** Services that are unavailable are reported as unavailable
  (503 / ``null`` / honest status payloads), never faked.
* **One data path.** The monitor is the single market-data pipeline.

The application currently runs **no trading strategy**: the historical
Fibonacci / EMA / liquidity / session strategies have been removed and the app
deliberately stays in a safe, non-trading state until a new strategy is
implemented. No signal is generated and no order is ever placed.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.connection import router as connection_router
from .api.execution import router as execution_router
from .api.health import router as health_router
from .api.market_data import router as market_router
from .api.reports import router as reports_router
from .api.websocket import router as websocket_router
from .config import PROJECT_ROOT, Settings, get_settings
from .errors import install_error_handlers
from .execution import ExecutionAuthorization, Mt5ExecutionAdapter
from .execution.authorization import DemoAccountVerifier
from .logging_config import setup_logging
from .mt5.connection import MT5Connection
from .services.market_monitor import MarketMonitor
from .storage import StatusStore

logger = logging.getLogger(__name__)

#: The phase label published by ``GET /``; tracked by the API contract tests.
PHASE = "phase-7-strategies-removed-no-trading"

#: Documented surface advertised by ``GET /``.
PUBLISHED_ENDPOINTS: tuple[str, ...] = (
    "/api/health",
    "/api/mt5/status",
    "/api/mt5/events",
    "/api/market/quote",
    "/api/market/candles",
    "/api/market/snapshot",
    "/api/market/timeframes",
    "/api/market/symbols",
    "/ws/market",
    "/api/execution/status",
    "/api/execution/enable",
    "/api/execution/assess",
    "/api/execution/history",
    "/api/reports",
)

#: Durable state lives next to the other runtime data (git-ignored).
DATABASE_PATH = PROJECT_ROOT / "backend" / "data" / "phase1_status.db"


def create_app(
    settings: Optional[Settings] = None,
    *,
    mt5_module: Any = None,
) -> FastAPI:
    """Build the FastAPI application.

    Args:
        settings: Validated settings; the cached environment settings when
            omitted.
        mt5_module: Optional MetaTrader module override (tests inject a fake;
            production passes ``None`` and the real package is imported).
    """
    settings = settings or get_settings()
    setup_logging(settings.log_level, settings.log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await _startup(app, settings, mt5_module)
        try:
            yield
        finally:
            await _shutdown(app)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Read-only XAUUSD market data from MetaTrader 5. No trading strategy "
            "is configured and no order is placed, modified or closed. Execution "
            "is demo-only, disabled by default and can only be armed by an "
            "explicit operator action."
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    install_error_handlers(app)

    app.include_router(health_router)
    app.include_router(connection_router)
    app.include_router(market_router)
    app.include_router(websocket_router)
    app.include_router(execution_router)
    app.include_router(reports_router)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, Any]:
        """Describe the running phase and the documented surface."""
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "phase": PHASE,
            "environment": settings.app_env,
            "read_only": True,
            "trading_enabled": False,
            "live_trading_supported": False,
            "endpoints": list(PUBLISHED_ENDPOINTS),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    return app


# ----------------------------------------------------------------------
# Lifespan
# ----------------------------------------------------------------------
async def _startup(app: FastAPI, settings: Settings, mt5_module: Any) -> None:
    """Build and start every shared service (best-effort, individually guarded)."""
    # An explicit DATABASE_PATH wins so a deployment (or a test) can point the
    # durable store at its own file; otherwise the default runtime location is
    # used.
    store_path = Path(settings.database_path) if settings.database_path else DATABASE_PATH
    store = StatusStore(store_path, enabled=settings.database_enabled)
    store.initialize()
    app.state.store = store

    connection = MT5Connection(settings, mt5_module=mt5_module)
    app.state.connection = connection

    monitor = MarketMonitor(connection, settings, store=store)
    app.state.monitor = monitor

    authorization = ExecutionAuthorization(DemoAccountVerifier(settings))
    app.state.execution_authorization = authorization
    app.state.execution_adapter = Mt5ExecutionAdapter(connection, authorization)

    connected = await connection.initialize()
    if not connected:
        logger.warning(
            "MT5 is not available at startup; the API will report degraded "
            "state and retry in the background."
        )

    await monitor.start()

    logger.info(
        "Application started (%s, read-only=%s, trading_enabled=%s)",
        PHASE,
        True,
        False,
    )


async def _shutdown(app: FastAPI) -> None:
    """Stop every shared service in reverse order; one failure never blocks the rest."""
    settings = getattr(app.state, "settings", None)
    store = getattr(app.state, "store", None)
    monitor = getattr(app.state, "monitor", None)
    connection = getattr(app.state, "connection", None)

    for name, component, method in (
        ("market monitor", monitor, "stop"),
        ("mt5 connection", connection, "shutdown"),
    ):
        stop = _as_coro(component, method)
        if stop is None:
            continue
        try:
            await stop()
        except Exception:  # noqa: BLE001 - shutdown must always complete
            logger.exception("Failed to stop the %s cleanly", name)

    if store is not None:
        try:
            store.close()
        except Exception:  # noqa: BLE001 - defensive
            logger.exception("Failed to close the status store cleanly")

    if settings is not None:
        logger.info("Application stopped")


def _as_coro(component: Any, method: str = "stop"):
    """Return ``component.method()`` when both exist, else ``None``."""
    if component is None:
        return None
    fn = getattr(component, method, None)
    if fn is None:
        return None
    return fn


__all__ = ["create_app", "PHASE", "PUBLISHED_ENDPOINTS"]
