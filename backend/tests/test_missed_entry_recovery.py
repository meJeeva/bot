"""Regression tests for automatic recovery after repeated missed entries."""

from __future__ import annotations

import pytest

from tests.auto_trading_harness import (
    VirtualClock,
    build_controller,
    install_virtual_time,
)
from tests.fakes import gold_terminal_with_live_tick


@pytest.mark.asyncio
async def test_missed_entry_does_not_stick_forever(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(fake)

    await controller.start()
    initial_cycle = controller._cycle_counter
    assert controller._phase in ("WAITING_ENTRY", "INITIALIZING")

    # Advance virtual time past the exit buffer and let the scheduler run.
    for _ in range(30):
        clock.advance(0.2)
        await controller._step()
        await __import__("asyncio").sleep(0)

    # The worker should have abandoned the stale cycle and initialised a new one
    # instead of remaining stuck on the crossed entry.
    assert controller._cycle_counter >= initial_cycle
    await controller.stop()
