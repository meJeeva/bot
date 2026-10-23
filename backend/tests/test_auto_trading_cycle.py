"""Smoke tests for the XAUUSD M1 stop-order strategy controller."""

from __future__ import annotations

import time

import pytest

from app.config import Settings
from tests.auto_trading_harness import (
    VirtualClock,
    build_controller,
    install_virtual_time,
    wait_for_status,
)
from tests.fakes import gold_terminal_with_live_tick


@pytest.mark.asyncio
async def test_status_endpoint_reports_m1_and_never_starts_trading(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import create_app

    settings = Settings(
        _env_file=None,
        database_enabled=False,
        log_level="WARNING",
        poll_interval_ms=200,
        auto_trade_max_cycles=5,
    )
    fake = gold_terminal_with_live_tick()
    app = create_app(settings, mt5_module=fake)

    with TestClient(app) as client:
        time.sleep(1)
        for _ in range(3):
            status = client.get("/api/auto-trading/status").json()
            assert status["status"] == "STOPPED"
            assert status["timeframe"] == "M1"

        assert [call for call in fake.calls if call[0] == "order_send"] == []

        assert client.post("/api/auto-trading/start").status_code == 200
        stopped = client.post("/api/auto-trading/stop").json()

        assert stopped["status"] == "STOPPED"
        assert stopped["position_status"] == "none"
        assert fake.positions == []


@pytest.mark.asyncio
async def test_duplicate_start_runs_a_single_loop(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_max_cycles=1000
    )

    await controller.start()
    first_task = controller._task
    session = controller._session_id
    assert first_task is not None and not first_task.done()

    second = await controller.start()

    assert second.status == "RUNNING"
    assert controller._task is first_task
    assert controller._session_id == session

    await controller.stop()


@pytest.mark.asyncio
async def test_stop_prevents_further_trading(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_max_cycles=1000
    )

    await controller.start()
    await controller.stop()

    status = await controller.status()
    assert status.status == "STOPPED"
    assert status.position_status == "none"
    assert fake.positions == []