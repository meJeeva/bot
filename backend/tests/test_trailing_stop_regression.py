"""Regression tests for fixed-gap and ATR trailing-stop behaviour."""

from __future__ import annotations

import asyncio

import pytest

from tests.auto_trading_harness import (
    VirtualClock,
    build_controller,
    install_virtual_time,
    _run_until_pending,
)
from tests.fakes import (
    gold_terminal_with_live_tick,
    FakePosition,
    FakeOrderResult,
)

MAGIC = 9001


def _set_price(fake, controller, bid, ask):
    controller.monitor.quote.bid = bid
    controller.monitor.quote.ask = ask
    fake.ticks["XAUUSD"].bid = bid
    fake.ticks["XAUUSD"].ask = ask


@pytest.mark.asyncio
async def test_buy_fixed_gap_trailing_follows_upward(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick(with_all_timeframes=True)
    controller, _connection, _settings = await build_controller(
        fake,
        auto_trade_entry_offset=1.00,
        auto_trade_break_even_offset=0.20,
        auto_trade_trailing_distance=0.20,
        xauusd_trailing_mode="fixed",
        auto_trade_max_cycles=5,
    )
    await controller.start()
    await _run_until_pending(controller, clock, fake)
    buy_orders = [o for o in fake.orders if o.type == 4]
    assert buy_orders
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

    _set_price(fake, controller, controller._buy_entry + 1.5, controller._buy_entry + 1.6)
    await _run_until_pending(controller, clock, fake)
    assert controller._break_even_active is True
    sl_after_activation = controller._current_sl

    _set_price(fake, controller, controller._buy_entry + 3.0, controller._buy_entry + 3.1)
    await _run_until_pending(controller, clock, fake)
    assert controller._current_sl is not None
    assert controller._current_sl > sl_after_activation
    # Exact-ish 0.20 gap subject to tick normalisation.
    assert abs((controller._buy_entry + 3.0) - controller._current_sl - 0.20) < 0.05
    await controller.stop()


@pytest.mark.asyncio
async def test_sell_fixed_gap_trailing_follows_downward(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick(with_all_timeframes=True)
    controller, _connection, _settings = await build_controller(
        fake,
        auto_trade_entry_offset=1.00,
        auto_trade_break_even_offset=0.20,
        auto_trade_trailing_distance=0.20,
        xauusd_trailing_mode="fixed",
        auto_trade_max_cycles=5,
    )
    await controller.start()
    await _run_until_pending(controller, clock, fake)
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

    _set_price(fake, controller, controller._sell_entry - 1.6, controller._sell_entry - 1.5)
    await _run_until_pending(controller, clock, fake)
    assert controller._break_even_active is True
    sl_after_activation = controller._current_sl

    _set_price(fake, controller, controller._sell_entry - 3.1, controller._sell_entry - 3.0)
    await _run_until_pending(controller, clock, fake)
    assert controller._current_sl is not None
    assert controller._current_sl < sl_after_activation
    await controller.stop()


@pytest.mark.asyncio
async def test_trailing_activates_only_after_point_two_profit(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick(with_all_timeframes=True)
    controller, _connection, _settings = await build_controller(
        fake,
        auto_trade_entry_offset=1.00,
        auto_trade_break_even_offset=0.20,
        auto_trade_trailing_distance=0.20,
        xauusd_trailing_mode="fixed",
        auto_trade_max_cycles=5,
    )
    await controller.start()
    await _run_until_pending(controller, clock, fake)
    buy_orders = [o for o in fake.orders if o.type == 4]
    bo = buy_orders[0]
    fake.orders = [o for o in fake.orders if o.ticket != bo.ticket]
    pos = FakePosition(
        ticket=5003,
        symbol="XAUUSD",
        magic=MAGIC,
        volume=0.01,
        price_open=controller._buy_entry,
        sl=controller._buy_sl,
        type=0,
    )
    fake.positions.append(pos)
    await _run_until_pending(controller, clock, fake)

    # Not enough profit: trailing must stay inactive.
    _set_price(fake, controller, controller._buy_entry + 0.10, controller._buy_entry + 0.11)
    await _run_until_pending(controller, clock, fake)
    assert controller._break_even_active is False

    # Enough profit: trailing activates.
    _set_price(fake, controller, controller._buy_entry + 0.30, controller._buy_entry + 0.31)
    await _run_until_pending(controller, clock, fake)
    assert controller._break_even_active is True
    await controller.stop()


@pytest.mark.asyncio
async def test_fixed_gap_sl_never_moves_backward(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick(with_all_timeframes=True)
    controller, _connection, _settings = await build_controller(
        fake,
        auto_trade_entry_offset=1.00,
        auto_trade_break_even_offset=0.20,
        auto_trade_trailing_distance=0.20,
        xauusd_trailing_mode="fixed",
        auto_trade_max_cycles=5,
    )
    await controller.start()
    await _run_until_pending(controller, clock, fake)
    buy_orders = [o for o in fake.orders if o.type == 4]
    bo = buy_orders[0]
    fake.orders = [o for o in fake.orders if o.ticket != bo.ticket]
    pos = FakePosition(
        ticket=5004,
        symbol="XAUUSD",
        magic=MAGIC,
        volume=0.01,
        price_open=controller._buy_entry,
        sl=controller._buy_sl,
        type=0,
    )
    fake.positions.append(pos)
    await _run_until_pending(controller, clock, fake)

    _set_price(fake, controller, controller._buy_entry + 3.0, controller._buy_entry + 3.1)
    await _run_until_pending(controller, clock, fake)
    high_sl = controller._current_sl

    _set_price(fake, controller, controller._buy_entry + 1.0, controller._buy_entry + 1.1)
    await _run_until_pending(controller, clock, fake)
    assert controller._current_sl >= high_sl
    await controller.stop()


@pytest.mark.asyncio
async def test_fast_price_changes_do_not_duplicate_sl_modifications(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick(with_all_timeframes=True)
    controller, _connection, _settings = await build_controller(
        fake,
        auto_trade_entry_offset=1.00,
        auto_trade_break_even_offset=0.20,
        auto_trade_trailing_distance=0.20,
        xauusd_trailing_mode="fixed",
        auto_trade_max_cycles=5,
    )
    await controller.start()
    await _run_until_pending(controller, clock, fake)
    buy_orders = [o for o in fake.orders if o.type == 4]
    bo = buy_orders[0]
    fake.orders = [o for o in fake.orders if o.ticket != bo.ticket]
    pos = FakePosition(
        ticket=5005,
        symbol="XAUUSD",
        magic=MAGIC,
        volume=0.01,
        price_open=controller._buy_entry,
        sl=controller._buy_sl,
        type=0,
    )
    fake.positions.append(pos)
    await _run_until_pending(controller, clock, fake)

    before = sum(1 for c in fake.calls if c[0] == "order_send")
    _set_price(fake, controller, controller._buy_entry + 3.0, controller._buy_entry + 3.1)
    await _run_until_pending(controller, clock, fake)
    after_first = sum(1 for c in fake.calls if c[0] == "order_send")
    # Same price again must not create another modification.
    await _run_until_pending(controller, clock, fake)
    after_second = sum(1 for c in fake.calls if c[0] == "order_send")
    assert after_second == after_first
    assert after_first > before
    await controller.stop()


@pytest.mark.asyncio
async def test_fixed_gap_rejected_modification_preserves_sl(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick(with_all_timeframes=True)
    controller, _connection, _settings = await build_controller(
        fake,
        auto_trade_entry_offset=1.00,
        auto_trade_break_even_offset=0.20,
        auto_trade_trailing_distance=0.20,
        xauusd_trailing_mode="fixed",
        auto_trade_max_cycles=5,
    )
    await controller.start()
    await _run_until_pending(controller, clock, fake)
    buy_orders = [o for o in fake.orders if o.type == 4]
    bo = buy_orders[0]
    fake.orders = [o for o in fake.orders if o.ticket != bo.ticket]
    pos = FakePosition(
        ticket=5006,
        symbol="XAUUSD",
        magic=MAGIC,
        volume=0.01,
        price_open=controller._buy_entry,
        sl=controller._buy_sl,
        type=0,
    )
    fake.positions.append(pos)
    await _run_until_pending(controller, clock, fake)

    _set_price(fake, controller, controller._buy_entry + 3.0, controller._buy_entry + 3.1)
    await _run_until_pending(controller, clock, fake)
    broker_sl_before = controller._current_sl

    fake.order_send_results = [FakeOrderResult(retcode=10013, comment="rejected")]
    target = broker_sl_before + 1.0 if broker_sl_before is not None else controller._buy_sl
    result = await controller._move_stop(pos, "buy", target, reason="test rejection")
    assert result is False
    assert controller._current_sl == broker_sl_before
    assert pos.sl == broker_sl_before

    # Resume after the retry window with a fresh, valid target.
    clock.advance(1.5)
    fake.ticks["XAUUSD"].bid = controller._buy_entry + 6.0
    fake.ticks["XAUUSD"].ask = controller._buy_entry + 6.1
    controller.monitor.quote.bid = controller._buy_entry + 6.0
    controller.monitor.quote.ask = controller._buy_entry + 6.1
    retry_target = broker_sl_before + 0.1
    fake.order_send_results = None
    result = await controller._move_stop(pos, "buy", retry_target, reason="retry after rejection")
    assert result is True
    assert controller._current_sl >= retry_target - 0.05
    await controller.stop()


@pytest.mark.asyncio
async def test_trailing_resumes_after_deferred_modification(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick(with_all_timeframes=True)
    controller, _connection, _settings = await build_controller(
        fake,
        auto_trade_entry_offset=1.00,
        auto_trade_break_even_offset=0.20,
        auto_trade_trailing_distance=0.20,
        xauusd_trailing_mode="fixed",
        auto_trade_max_cycles=5,
    )
    await controller.start()
    await _run_until_pending(controller, clock, fake)
    buy_orders = [o for o in fake.orders if o.type == 4]
    bo = buy_orders[0]
    fake.orders = [o for o in fake.orders if o.ticket != bo.ticket]
    pos = FakePosition(
        ticket=5008,
        symbol="XAUUSD",
        magic=MAGIC,
        volume=0.01,
        price_open=controller._buy_entry,
        sl=controller._buy_sl,
        type=0,
    )
    fake.positions.append(pos)
    await _run_until_pending(controller, clock, fake)

    _set_price(fake, controller, controller._buy_entry + 3.0, controller._buy_entry + 3.1)
    await _run_until_pending(controller, clock, fake)
    sl_before = controller._current_sl

    # Defer modifications temporarily.
    controller._sl_retry_at = clock.now() + 10.0
    _set_price(fake, controller, controller._buy_entry + 4.0, controller._buy_entry + 4.1)
    await _run_until_pending(controller, clock, fake)

    # Retry window expires; trailing resumes.
    clock.advance(11.0)
    _set_price(fake, controller, controller._buy_entry + 5.0, controller._buy_entry + 5.1)
    fake.ticks["XAUUSD"].bid = controller._buy_entry + 5.0
    fake.ticks["XAUUSD"].ask = controller._buy_entry + 5.1
    await _run_until_pending(controller, clock, fake)
    assert controller._current_sl > sl_before
    await controller.stop()


@pytest.mark.asyncio
async def test_atr_break_even_continues_working_independently(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick(with_all_timeframes=True)
    controller, _connection, _settings = await build_controller(
        fake,
        auto_trade_entry_offset=1.00,
        auto_trade_break_even_offset=0.20,
        auto_trade_trailing_distance=0.40,
        xauusd_trailing_mode="atr",
        xauusd_trail_atr_multiplier=0.2,
        auto_trade_max_cycles=5,
    )
    await controller.start()
    await _run_until_pending(controller, clock, fake)
    buy_orders = [o for o in fake.orders if o.type == 4]
    bo = buy_orders[0]
    fake.orders = [o for o in fake.orders if o.ticket != bo.ticket]
    pos = FakePosition(
        ticket=5007,
        symbol="XAUUSD",
        magic=MAGIC,
        volume=0.01,
        price_open=controller._buy_entry,
        sl=controller._buy_sl,
        type=0,
    )
    fake.positions.append(pos)
    await _run_until_pending(controller, clock, fake)

    _set_price(fake, controller, controller._buy_entry + 1.5, controller._buy_entry + 1.6)
    await _run_until_pending(controller, clock, fake)
    assert controller._break_even_active is True
    assert controller._last_trail_atr is not None
    await controller.stop()
