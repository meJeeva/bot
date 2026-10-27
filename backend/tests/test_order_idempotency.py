"""Regression tests for idempotent MT5 order/stop management."""

from __future__ import annotations

import asyncio

import pytest

from tests.auto_trading_harness import VirtualClock, install_virtual_time
from tests.test_btcusd_support import build_btc_controller, _run_until_pending, btc_fake
from tests.fakes import FakePosition


MAGIC = 9001


def _sltp_count(fake):
    return sum(1 for call in fake.calls if call[0] == "order_send")


@pytest.mark.asyncio
async def test_unchanged_stop_loss_does_not_trigger_sltp(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = btc_fake()
    controller, _connection, _settings = await build_btc_controller(fake)

    await controller.start()
    await _run_until_pending(controller, clock, fake)

    buy_orders = [o for o in fake.orders if o.type == 4]
    assert buy_orders, "expected a Buy Stop"
    buy = buy_orders[0]
    fake.orders = [o for o in fake.orders if o.ticket != buy.ticket]
    position = FakePosition(
        ticket=7001,
        symbol="BTCUSD",
        magic=MAGIC,
        volume=0.05,
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
    fake = btc_fake()
    controller, _connection, _settings = await build_btc_controller(fake)

    await controller.start()
    await _run_until_pending(controller, clock, fake)

    buy_orders = [o for o in fake.orders if o.type == 4]
    assert buy_orders, "expected a Buy Stop"
    buy = buy_orders[0]
    fake.orders = [o for o in fake.orders if o.ticket != buy.ticket]
    position = FakePosition(
        ticket=7002,
        symbol="BTCUSD",
        magic=MAGIC,
        volume=0.05,
        price_open=controller._buy_entry,
        sl=controller._buy_sl,
        type=0,
    )
    fake.positions.append(position)
    await _run_until_pending(controller, clock, fake)

    assert controller._position_ticket == 7002

    position.sl = controller._current_sl
    new_target = controller._current_sl + 10.0
    before = _sltp_count(fake)
    result = await controller._move_stop(position, "buy", new_target, reason="legitimate change")
    after = _sltp_count(fake)
    assert after == before + 1, "a legitimate change must trigger exactly one modification"
    assert result is True