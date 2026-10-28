"""Regression tests for side_removed and entry success/failure reporting."""

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


@pytest.mark.asyncio
async def test_successful_entry_cancels_opposing_order_once(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(fake, auto_trade_entry_offset=1.00, auto_trade_break_even_offset=0.40, auto_trade_trailing_distance=0.40)

    await controller.start()
    await _run_until_pending(controller, clock, fake)

    # Both pending orders should exist.
    assert any(o.type == 4 for o in fake.orders)  # buy stop
    assert any(o.type == 5 for o in fake.orders)  # sell stop

    # Simulate the buy stop triggering: remove it from broker and add a position.
    buy_orders = [o for o in fake.orders if o.type == 4]
    assert buy_orders
    buy_ticket = buy_orders[0].ticket
    fake.orders = [o for o in fake.orders if o.ticket != buy_ticket]
    position = FakePosition(
        ticket=8001,
        symbol="XAUUSD",
        magic=MAGIC,
        volume=0.01,
        price_open=controller._buy_entry,
        sl=controller._buy_sl,
        type=0,
    )
    fake.positions.append(position)

    # Drive price to the buy entry so the buy trigger fires.
    controller.monitor.quote = __import__("types").SimpleNamespace(
        bid=controller._buy_entry,
        ask=controller._buy_entry + 0.5,
        spread_points=56.0,
        is_stale=False,
    )

    await _run_until_pending(controller, clock, fake, steps=5)

    # Sell stop must be cancelled exactly once and never re-placed.
    assert controller._side_removed.get("sell") is True
    assert controller._sell_order_ticket is None
    assert not any(o.type == 5 for o in fake.orders), "sell stop must not be re-placed"

    # The buy position must be adopted and managed.
    assert controller._active_side == "buy"
    assert controller._position_ticket == 8001

    await controller.stop()


@pytest.mark.asyncio
async def test_failed_entry_is_not_reported_as_success(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    # Broker rejects every pending submission.
    fake.order_send_retcode = 10016

    controller, _connection, _settings = await build_controller(fake, auto_trade_entry_offset=1.00, auto_trade_break_even_offset=0.40, auto_trade_trailing_distance=0.40)

    await controller.start()
    await _run_until_pending(controller, clock, fake, steps=5)

    # No order should be confirmed and no success result reported.
    assert controller._buy_order_ticket is None or controller._buy_order_ticket not in {
        o.ticket for o in fake.orders
    }
    assert controller._sell_order_ticket is None or controller._sell_order_ticket not in {
        o.ticket for o in fake.orders
    }
    # A retry must have been scheduled (not a silent success).
    assert controller._order_retry_at.get("buy", 0) > 0 or controller._order_retry_at.get("sell", 0) > 0
    # No ENTRY_CONFIRMED should have been recorded as last_entry_result.
    last = controller._last_entry_result or ""
    assert "confirmed" not in last.lower() or "ambiguous" in last.lower()

    await controller.stop()
