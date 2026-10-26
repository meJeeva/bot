"""Stop policies and session handling for the XAUUSD M1 strategy."""

from __future__ import annotations

import asyncio

import pytest

from app.config import Settings
from tests.auto_trading_harness import (
    VirtualClock,
    build_controller,
    install_virtual_time,
)
from tests.fakes import gold_terminal_with_live_tick


@pytest.mark.asyncio
async def test_stop_close_policy_cancels_pending_orders(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_max_cycles=1000, auto_trade_stop_policy="close"
    )

    await controller.start()
    await asyncio.sleep(0.05)
    status = await controller.stop()

    assert status.status == "STOPPED"
    assert fake.orders == []
    assert fake.positions == []


@pytest.mark.asyncio
async def test_stop_leave_policy_also_cancels_pending_orders(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_max_cycles=1000, auto_trade_stop_policy="leave"
    )

    await controller.start()
    await asyncio.sleep(0.05)
    status = await controller.stop()

    assert status.status == "STOPPED"
    assert fake.orders == []


def test_stop_policy_defaults_and_validation():
    assert Settings(_env_file=None, database_enabled=False).auto_trade_stop_policy == "close"
    assert (
        Settings(
            _env_file=None, database_enabled=False, auto_trade_stop_policy="leave"
        ).auto_trade_stop_policy
        == "leave"
    )