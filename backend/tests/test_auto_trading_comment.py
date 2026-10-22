"""MT5 order comments for the automatic-trading strategy.

Comments stay within MT5's 31-character limit and identify the entry/exit side
of the cycle. The comment prefix is independent of the scheduler.
"""

from __future__ import annotations

import pytest

from app.services.auto_trading import _make_comment
from tests.auto_trading_harness import (
    VirtualClock,
    build_controller,
    entries,
    exits,
    install_virtual_time,
    instrument_orders,
    wait_for_status,
)
from tests.fakes import gold_terminal_with_live_tick


def test_comment_format_function():
    """Test the _make_comment helper directly."""
    # Normal cases
    assert _make_comment("AU_M1_B", 1) == "AU_M1_B1"
    assert _make_comment("AU_M1_B", 99) == "AU_M1_B99"
    assert _make_comment("AU_M1_C", 1) == "AU_M1_C1"
    assert _make_comment("AU_M1_C", 999) == "AU_M1_C999"

    # All comments must be <= 31 characters
    for i in [1, 10, 100, 1000, 9999, 99999]:
        entry_comment = _make_comment("AU_M1_B", i)
        exit_comment = _make_comment("AU_M1_C", i)
        assert len(entry_comment) <= 31, f"Entry comment too long at cycle {i}: {entry_comment}"
        assert len(exit_comment) <= 31, f"Exit comment too long at cycle {i}: {exit_comment}"


@pytest.mark.asyncio
async def test_entry_and_exit_comments_are_short(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_max_cycles=1
    )
    events = []
    instrument_orders(fake, clock, events, 9001)

    await controller.start()
    await wait_for_status(controller, {"STOPPED", "ERROR"})

    buys = entries(events)
    sells = exits(events)
    assert len(buys) == 1, "expected one entry order"
    assert len(sells) == 1, "expected one exit order"

    entry_comment = buys[0].request["comment"]
    exit_comment = sells[0].request["comment"]
    assert len(entry_comment) <= 31, f"Comment too long: {len(entry_comment)} chars"
    assert entry_comment == "AU_M1_B1"
    assert len(exit_comment) <= 31, f"Exit comment too long: {len(exit_comment)} chars"
    assert exit_comment == "AU_M1_C1"
