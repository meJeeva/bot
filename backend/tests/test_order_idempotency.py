"""Regression tests for idempotent MT5 order/stop management."""

from __future__ import annotations

import asyncio

import pytest

from tests.auto_trading_harness import (
    VirtualClock,
    _run_until_pending,
    build_controller,
    install_virtual_time,
)
from tests.fakes import FakePosition, gold_terminal_with_live_tick


MAGIC = 9001


def _sltp_count(fake):
    return sum(1 for call in fake.calls if call[0] == "order_send")


@pytest.mark.asyncio
async def test_unchanged_stop_loss_does_not_trigger_sltp(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(fake, auto_trade_entry_offset=1.00, auto_trade_break_even_offset=0.40, auto_trade_trailing_distance=0.40)

    await controller.start()
    await _run_until_pending(controller, clock, fake)

    buy_orders = [o for o in fake.orders if o.type == 4]
    assert buy_orders, "expected a Buy Stop"
    buy = buy_orders[0]
    fake.orders = [o for o in fake.orders if o.ticket != buy.ticket]
    position = FakePosition(
        ticket=7001,
        symbol="XAUUSD",
        magic=MAGIC,
        volume=0.01,
        price_open=controller._buy_entry,
        sl=controller._buy_sl,
        type=0,
    )
    fake.positions.append(position)
    await _run_until_pending(controller, clock, fake)

    assert controller._position_ticket == 7001

    position.sl = controller._current_sl
    before = _sltp_count(fake)
    result = await controller._move_stop(
        position, "buy", controller._current_sl, reason="idempotency check"
    )
    after = _sltp_count(fake)
    assert after == before, "unchanged stop must not trigger a modification"
    assert result is True


@pytest.mark.asyncio
async def test_legitimate_stop_change_still_triggers_sltp(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(fake, auto_trade_entry_offset=1.00, auto_trade_break_even_offset=0.40, auto_trade_trailing_distance=0.40)

    await controller.start()
    await _run_until_pending(controller, clock, fake)

    buy_orders = [o for o in fake.orders if o.type == 4]
    assert buy_orders, "expected a Buy Stop"
    buy = buy_orders[0]
    fake.orders = [o for o in fake.orders if o.ticket != buy.ticket]
    position = FakePosition(
        ticket=7002,
        symbol="XAUUSD",
        magic=MAGIC,
        volume=0.01,
        price_open=controller._buy_entry,
        sl=controller._buy_sl,
        type=0,
    )
    fake.positions.append(position)
    await _run_until_pending(controller, clock, fake)

    assert controller._position_ticket == 7002

    # A change a broker would actually accept: the tracked SL is re-based to
    # a protective level 1.00 below the current Bid, and the target moves it
    # closer without ever reaching the Bid (a BUY SL at or above the Bid is
    # the wrong market side and is deferred, never submitted).
    bid = fake.ticks["XAUUSD"].bid
    position.sl = controller._current_sl = bid - 10.0
    new_target = bid - 5.0
    before = _sltp_count(fake)
    result = await controller._move_stop(position, "buy", new_target, reason="legitimate change")
    after = _sltp_count(fake)
    assert after == before + 1, "a legitimate change must trigger exactly one modification"
    assert result is True
