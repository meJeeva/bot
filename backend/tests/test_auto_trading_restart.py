"""Regression tests for automatic restart after a confirmed stop-loss."""

from __future__ import annotations

import asyncio

import pytest

from tests.auto_trading_harness import (
    VirtualClock,
    build_controller,
    install_virtual_time,
)
from tests.fakes import FakeDeal, FakeOrderResult, FakePosition, gold_terminal_with_live_tick


MAGIC = 9001


async def _run_until_pending(controller, clock, fake, steps=20):
    for _ in range(steps):
        clock.advance(0.2)
        await asyncio.sleep(0.05)


async def _fill_buy(controller, clock, fake):
    await _run_until_pending(controller, clock, fake)
    buy_orders = [o for o in fake.orders if o.type == 4]
    assert buy_orders, "expected a Buy Stop"
    bo = buy_orders[0]
    fake.orders = [o for o in fake.orders if o.ticket != bo.ticket]
    pos = FakePosition(
        ticket=5001,
        symbol="XAUUSD",
        magic=MAGIC,
        volume=0.01,
        price_open=controller._buy_entry,
        sl=controller._buy_sl,
        type=0,
    )
    fake.positions.append(pos)
    await _run_until_pending(controller, clock, fake)
    return pos


async def _hit_sl(controller, clock, fake, pos, deal_id=9001):
    fake.positions = [p for p in fake.positions if p.ticket != pos.ticket]
    deal = FakeDeal(
        ticket=deal_id,
        position_id=pos.ticket,
        position=pos.ticket,
        price=controller._current_sl,
        profit=-1.0,
        comment="sl",
        reason=4,
        entry=1,
    )
    fake.deals.append(deal)
    await _run_until_pending(controller, clock, fake)


@pytest.mark.asyncio
async def test_confirmed_buy_sl_starts_one_next_cycle(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_entry_offset=1.00, auto_trade_break_even_offset=0.40, auto_trade_trailing_distance=0.40, auto_trade_max_cycles=5
    )
    await controller.start()
    pos = await _fill_buy(controller, clock, fake)
    before_orders = [o.ticket for o in fake.orders]
    assert before_orders == [], "opposing pending should be removed"

    await _hit_sl(controller, clock, fake, pos)
    assert controller._completed_cycles == 1
    assert controller._phase in ("WAITING_ENTRY", "INITIALIZING", "SWITCHING")
    assert len([o for o in fake.orders if o.type in (4, 5)]) == 2
    await controller.stop()


@pytest.mark.asyncio
async def test_confirmed_sell_sl_starts_one_next_cycle(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_entry_offset=1.00, auto_trade_break_even_offset=0.40, auto_trade_trailing_distance=0.40, auto_trade_max_cycles=5
    )
    await controller.start()
    await _run_until_pending(controller, clock, fake)
    # force a sell fill instead of buy
    sell_orders = [o for o in fake.orders if o.type == 5]
    assert sell_orders
    so = sell_orders[0]
    fake.orders = [o for o in fake.orders if o.ticket != so.ticket]
    pos = FakePosition(
        ticket=5002,
        symbol="XAUUSD",
        magic=MAGIC,
        volume=0.01,
        price_open=controller._sell_entry,
        sl=controller._sell_sl,
        type=1,
    )
    fake.positions.append(pos)
    await _run_until_pending(controller, clock, fake)
    assert controller._active_side == "sell"

    await _hit_sl(controller, clock, fake, pos, deal_id=9002)
    assert controller._completed_cycles == 1
    assert len([o for o in fake.orders if o.type in (4, 5)]) == 2
    await controller.stop()


@pytest.mark.asyncio
async def test_trailing_be_sl_starts_next_cycle(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_entry_offset=1.00, auto_trade_break_even_offset=0.40, auto_trade_trailing_distance=0.40, auto_trade_max_cycles=5
    )
    await controller.start()
    pos = await _fill_buy(controller, clock, fake)
    # move price to activate break-even
    controller.monitor.quote.bid = controller._buy_entry + 1.5
    controller.monitor.quote.ask = controller._buy_entry + 1.6
    await _run_until_pending(controller, clock, fake)
    assert controller._break_even_active is True
    sl_before = controller._current_sl
    # hit at trailed sl
    fake.positions = [p for p in fake.positions if p.ticket != pos.ticket]
    deal = FakeDeal(
        ticket=9003,
        position_id=pos.ticket,
        position=pos.ticket,
        price=sl_before,
        profit=-0.5,
        comment="sl",
        reason=4,
        entry=1,
    )
    fake.deals.append(deal)
    await _run_until_pending(controller, clock, fake)
    assert controller._completed_cycles == 1
    await controller.stop()


@pytest.mark.asyncio
async def test_next_reference_uses_latest_price(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick(bid=4185.58, ask=4186.14)
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_entry_offset=1.00, auto_trade_break_even_offset=0.40, auto_trade_trailing_distance=0.40, auto_trade_max_cycles=5
    )
    await controller.start()
    pos = await _fill_buy(controller, clock, fake)
    old_ref = controller._reference_value
    # latest market price available to the next cycle
    controller.monitor.quote.bid = 4200.0
    controller.monitor.quote.ask = 4200.5
    await _hit_sl(controller, clock, fake, pos)
    await _run_until_pending(controller, clock, fake, steps=5)
    assert controller._reference_value != old_ref
    await controller.stop()


@pytest.mark.asyncio
async def test_duplicate_deal_does_not_duplicate_cycle(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_entry_offset=1.00, auto_trade_break_even_offset=0.40, auto_trade_trailing_distance=0.40, auto_trade_max_cycles=5
    )
    await controller.start()
    pos = await _fill_buy(controller, clock, fake)
    await _hit_sl(controller, clock, fake, pos)
    cycles_after_first = controller._completed_cycles
    orders_after_first = len(fake.orders)
    # replay same deal notification
    await _run_until_pending(controller, clock, fake)
    assert controller._completed_cycles == cycles_after_first
    assert len(fake.orders) == orders_after_first
    await controller.stop()


@pytest.mark.asyncio
async def test_delayed_deal_history_handled(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_entry_offset=1.00, auto_trade_break_even_offset=0.40, auto_trade_trailing_distance=0.40, auto_trade_max_cycles=5
    )
    await controller.start()
    pos = await _fill_buy(controller, clock, fake)
    # remove position but delay deal
    fake.positions = [p for p in fake.positions if p.ticket != pos.ticket]
    await _run_until_pending(controller, clock, fake, steps=5)
    # no false switch yet
    assert controller._completed_cycles == 0
    # now provide deal
    deal = FakeDeal(
        ticket=9010,
        position_id=pos.ticket,
        position=pos.ticket,
        price=controller._current_sl,
        profit=-1.0,
        comment="sl",
        reason=4,
        entry=1,
    )
    fake.deals.append(deal)
    await _run_until_pending(controller, clock, fake)
    assert controller._completed_cycles == 1
    await controller.stop()


@pytest.mark.asyncio
async def test_three_sequential_sl_cycles(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_entry_offset=1.00, auto_trade_break_even_offset=0.40, auto_trade_trailing_distance=0.40, auto_trade_max_cycles=10
    )
    await controller.start()
    for i in range(3):
        pos = await _fill_buy(controller, clock, fake) if i == 0 else None
        if i > 0:
            # fill next cycle's buy
            await _run_until_pending(controller, clock, fake)
            buy_orders = [o for o in fake.orders if o.type == 4]
            assert buy_orders
            bo = buy_orders[0]
            fake.orders = [o for o in fake.orders if o.ticket != bo.ticket]
            pos = FakePosition(
                ticket=5100 + i,
                symbol="XAUUSD",
                magic=MAGIC,
                volume=0.01,
                price_open=controller._buy_entry,
                sl=controller._buy_sl,
                type=0,
            )
            fake.positions.append(pos)
            await _run_until_pending(controller, clock, fake)
        await _hit_sl(controller, clock, fake, pos, deal_id=9100 + i)
    assert controller._completed_cycles == 3
    await controller.stop()


@pytest.mark.asyncio
async def test_stop_prevents_further_entries(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_entry_offset=1.00, auto_trade_break_even_offset=0.40, auto_trade_trailing_distance=0.40, auto_trade_max_cycles=10
    )
    await controller.start()
    await _run_until_pending(controller, clock, fake)
    await controller.stop()
    orders_before = len(fake.orders)
    await asyncio.sleep(0.1)
    assert len(fake.orders) == orders_before
    assert controller._status == "STOPPED"


@pytest.mark.asyncio
async def test_rejected_entry_no_false_success(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_entry_offset=1.00, auto_trade_break_even_offset=0.40, auto_trade_trailing_distance=0.40, auto_trade_max_cycles=5
    )
    # make first entry submission rejected
    fake.order_send_results = [FakeOrderResult(retcode=10016, comment="invalid stops")]
    await controller.start()
    await _run_until_pending(controller, clock, fake, steps=5)
    assert controller._failed_entries >= 1
    await controller.stop()
