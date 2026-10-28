"""Regression tests for side-specific XAUUSD entry offsets and the
independent initial stop-loss distance.

Required values for a cycle reference of 4030.92:

* Buy entry  = reference + 0.47 = 4031.39, Buy initial SL  = 4031.39 - 0.20
* Sell entry = reference - 0.32 = 4030.60, Sell initial SL = 4030.60 + 0.20

Everything here runs against the faked terminal; no real order is placed.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import Settings
from app.strategy.range_break_even import build_cycle_levels
from tests.auto_trading_harness import (
    VirtualClock,
    build_controller,
    install_virtual_time,
)
from tests.fakes import (
    ORDER_TYPE_BUY_STOP,
    ORDER_TYPE_SELL_STOP,
    FakeTick,
    broker_time,
    gold_terminal_with_live_tick,
)

REFERENCE = 4030.92
BUY_ENTRY = 4031.39
BUY_SL = 4031.19
SELL_ENTRY = 4030.60
SELL_SL = 4030.80


def _xauusd_overrides() -> dict:
    """The operator's XAUUSD profile, with the old entry offset still present."""
    return {
        "auto_trade_profile": "XAUUSD",
        "xauusd_entry_offset": 1.00,
        "xauusd_break_even_offset": 0.20,
        "xauusd_trailing_distance": 0.20,
        "xauusd_lot_size": 0.01,
        "xauusd_buy_entry_offset": 0.47,
        "xauusd_sell_entry_offset": 0.32,
        "xauusd_initial_sl_distance": 0.20,
    }


def test_exact_levels_for_reference_4030_92():
    levels = build_cycle_levels(
        REFERENCE,
        tick_size=0.01,
        digits=2,
        buy_entry_offset=0.47,
        sell_entry_offset=0.32,
        initial_sl_distance=0.20,
    )
    assert levels.reference == REFERENCE
    assert levels.buy_entry == BUY_ENTRY
    assert levels.buy_sl == BUY_SL
    assert levels.sell_entry == SELL_ENTRY
    assert levels.sell_sl == SELL_SL


def test_omitted_side_parameters_reproduce_the_symmetric_levels():
    levels = build_cycle_levels(REFERENCE, tick_size=0.01, digits=2, entry_offset=1.00)
    assert levels.buy_entry == 4031.92
    assert levels.buy_sl == 4030.92
    assert levels.sell_entry == 4029.92
    assert levels.sell_sl == 4030.92


def test_xauusd_profile_resolves_side_settings_over_the_old_entry_offset():
    settings = Settings(_env_file=None, database_enabled=False, **_xauusd_overrides())
    assert settings.auto_trade_entry_offset == 1.00
    assert settings.auto_trade_buy_entry_offset == 0.47
    assert settings.auto_trade_sell_entry_offset == 0.32
    assert settings.auto_trade_initial_sl_distance == 0.20


def test_missing_side_settings_fall_back_to_the_entry_offset():
    settings = Settings(
        _env_file=None,
        database_enabled=False,
        auto_trade_profile="XAUUSD",
        xauusd_entry_offset=1.00,
    )
    assert settings.auto_trade_buy_entry_offset == 1.00
    assert settings.auto_trade_sell_entry_offset == 1.00
    assert settings.auto_trade_initial_sl_distance == 1.00


@pytest.mark.asyncio
async def test_controller_reads_the_side_specific_settings():
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, **_xauusd_overrides()
    )
    assert controller._entry_offset == 1.00
    assert controller._buy_entry_offset == 0.47
    assert controller._sell_entry_offset == 0.32
    assert controller._initial_sl_distance == 0.20


@pytest.mark.asyncio
async def test_controller_defaults_every_distance_to_the_entry_offset():
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(fake)
    assert controller._entry_offset == 0.20
    assert controller._buy_entry_offset == controller._entry_offset
    assert controller._sell_entry_offset == controller._entry_offset
    assert controller._initial_sl_distance == controller._entry_offset


@pytest.mark.asyncio
async def test_controller_places_pending_orders_at_the_side_specific_levels(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, **_xauusd_overrides()
    )
    controller._tick_size = 0.01
    controller._digits = 2
    controller.monitor.quote = SimpleNamespace(
        bid=4030.90, ask=4030.94, spread_points=4.0, is_stale=False
    )
    # The broker tick must agree with the monitor quote: the controller
    # validates every stop against a freshly-read tick, so a stale or
    # unrelated tick would (correctly) report the level as already crossed.
    fake.set_tick(
        "XAUUSD",
        FakeTick(time=broker_time(), bid=4030.90, ask=4030.94),
    )

    await controller._initialize_cycle(controller.monitor.latest_quote())

    assert controller._reference_value == REFERENCE
    assert controller._buy_entry == BUY_ENTRY
    assert controller._buy_sl == BUY_SL
    assert controller._sell_entry == SELL_ENTRY
    assert controller._sell_sl == SELL_SL

    buy = next(o for o in fake.orders if o.type == ORDER_TYPE_BUY_STOP)
    sell = next(o for o in fake.orders if o.type == ORDER_TYPE_SELL_STOP)
    assert buy.price == BUY_ENTRY
    assert buy.sl == BUY_SL
    assert sell.price == SELL_ENTRY
    assert sell.sl == SELL_SL


@pytest.mark.asyncio
async def test_adopted_buy_fill_derives_side_specific_levels_and_initial_sl(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, **_xauusd_overrides()
    )
    controller._tick_size = 0.01
    controller._digits = 2
    controller.monitor.quote = SimpleNamespace(
        bid=4030.90, ask=4030.94, spread_points=4.0, is_stale=False
    )
    # A buy fill at 4031.50 adopted without a cycle: the reference must be
    # recovered with the BUY offset (fill - 0.47) and the initial SL must sit
    # 0.20 below the actual fill (4031.30), not below the reference.
    position = SimpleNamespace(
        ticket=12345, type=0, price_open=4031.50, volume=0.01, sl=0.0, profit=0.0
    )

    await controller._adopt_position(position, quote=controller.monitor.latest_quote())

    assert controller._active_side == "buy"
    assert controller._reference_value == 4031.03
    assert controller._buy_entry == 4031.50
    assert controller._sell_entry == 4030.71
    assert controller._current_sl == 4031.30
