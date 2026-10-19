"""Shared test fixtures.

Everything here is mock-based. No test in this directory touches a real
MetaTrader 5 terminal; that is the job of
``tests/integration/test_live_mt5.py`` (marked ``live``).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Callable

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:  # pragma: no cover - safety net
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import Settings  # noqa: E402
from app.mt5.connection import MT5Connection  # noqa: E402
from app.services.market_monitor import MarketMonitor  # noqa: E402
from tests.fakes import (  # noqa: E402
    DEFAULT_SERVER_OFFSET_SECONDS,
    FakeMT5,
    gold_terminal_with_live_tick,
)

__all__ = [
    "api_client",
    "connection",
    "fake_mt5",
    "gold_terminal_with_live_tick",
    "isolated_environment",
    "make_settings",
    "monitor",
    "server_offset",
    "settings",
    "wait_until",
]

# Environment variable names the application understands. Tests start from a
# clean slate so a developer's shell cannot change the outcome.
_APP_ENV_NAMES = [name.upper() for name in Settings.model_fields]


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every application environment variable before each test."""
    for name in _APP_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def make_settings():
    """Factory for validated settings that ignore ``.env`` files."""

    def _make(**overrides):
        overrides.setdefault("database_enabled", False)
        overrides.setdefault("log_level", "WARNING")
        return Settings(_env_file=None, **overrides)

    return _make


@pytest.fixture
def settings(make_settings) -> Settings:
    return make_settings()


@pytest.fixture
def fake_mt5() -> FakeMT5:
    return gold_terminal_with_live_tick()


@pytest.fixture
def connection(settings: Settings, fake_mt5: FakeMT5) -> MT5Connection:
    return MT5Connection(settings, mt5_module=fake_mt5)


@pytest.fixture
def monitor(settings: Settings, connection: MT5Connection) -> MarketMonitor:
    return MarketMonitor(connection, settings)


@pytest.fixture
def api_client(make_settings, fake_mt5: FakeMT5):
    """A TestClient wired to a fake terminal, with the real app lifespan.

    The polling interval is short so tests do not have to wait a second for
    the monitor's first pass.
    """
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(
        make_settings(poll_interval_ms=200, ws_push_interval_ms=200),
        mt5_module=fake_mt5,
    )
    with TestClient(app) as client:
        yield client


@pytest.fixture
def wait_until() -> Callable[..., bool]:
    """Poll ``predicate`` until it is true or the timeout expires."""

    def _wait(predicate: Callable[[], bool], timeout: float = 8.0, interval: float = 0.05) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if predicate():
                    return True
            except Exception:  # pragma: no cover - transient during startup
                pass
            time.sleep(interval)
        return False

    return _wait


@pytest.fixture
def server_offset() -> int:
    return DEFAULT_SERVER_OFFSET_SECONDS
