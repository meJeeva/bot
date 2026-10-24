"""BTCUSD support: configuration profile, metadata validation and lifecycle.

Every test drives the real controller (or the real configuration model)
against the mocked MT5 adapter in ``tests.fakes``. No test places a real
order and none needs a live terminal. The XAUUSD regression suite must keep
passing unchanged alongside this file.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.mt5.connection import MT5Connection
from app.mt5.symbols import SymbolResolutionStatus, discover_symbol
from app.services.auto_trading import AutoTradingController
from tests.auto_trading_harness import (
    FakeMonitor,
    VirtualClock,
    build_controller,
    install_virtual_time,
    wait_for,
)
from tests.fakes import (
    DEFAULT_SERVER_OFFSET_SECONDS,
    FakeDeal,
    FakePosition,
    FakeSymbolInfo,
    FakeTick,
    FakeMT5,
    broker_time,
)

MAGIC = 9001

BTC_SETTINGS = dict(
    mt5_symbol="BTCUSD",
    mt5_symbol_candidates="BTCUSD,BTCUSD.,BTCUSDm,BTCUSD.c,#BTCUSD",
    auto_trade_entry_offset=50.0,
    auto_trade_break_even_offset=25.0,
    auto_trade_trailing_distance=15.0,
    auto_trade_lot_size=0.05,
    auto_trade_max_spread_points=2000.0,
)

BTC_REFERENCE = 104_006.0  # mid of the fake BTCUSD bid/ask below


def btc_fake(**symbol_overrides) -> FakeMT5:
    """A terminal that offers only a BTCUSD broker variant - no XAUUSD."""
    info_kwargs = dict(
        digits=2,
        point=0.01,
        trade_tick_size=0.01,
        currency_base="BTC",
        volume_min=0.01,
        volume_max=50.0,
        volume_step=0.01,
        spread=1200,
    )
    info_kwargs.update(symbol_overrides)
    info = FakeSymbolInfo("BTCUSD", **info_kwargs)
    return FakeMT5(
        symbols=[info],
        ticks={"BTCUSD": FakeTick(time=broker_time(), bid=104_000.0, ask=104_012.0)},
    )


async def build_btc_controller(fake: FakeMT5, **overrides):
    """A controller over the BTCUSD profile with BTC-scale monitor quotes."""
    overrides = {**BTC_SETTINGS, **overrides}
    controller, connection, settings = await build_controller(fake, **overrides)
    controller.monitor = FakeMonitor(symbol="BTCUSD", spread_points=500.0)
    controller.monitor.quote = SimpleNamespace(
        bid=104_000.0, ask=104_012.0, spread_points=500.0, is_stale=False
    )
    return controller, connection, settings


async def _run_until_pending(controller, clock, fake, steps=20):
    for _ in range(steps):
        clock.advance(0.2)
        await asyncio.sleep(0.05)


# ======================================================================
# Configuration profile
# ======================================================================
class TestBtcusdConfiguration:
    def test_missing_explicit_values_block_the_profile(self):
        for incomplete in (
            {"auto_trade_break_even_offset": 25.0, "auto_trade_trailing_distance": 15.0, "auto_trade_lot_size": 0.05},
            {"auto_trade_entry_offset": 50.0, "auto_trade_trailing_distance": 15.0, "auto_trade_lot_size": 0.05},
            {"auto_trade_entry_offset": 50.0, "auto_trade_break_even_offset": 25.0, "auto_trade_lot_size": 0.05},
            {"auto_trade_entry_offset": 50.0, "auto_trade_break_even_offset": 25.0, "auto_trade_trailing_distance": 15.0},
        ):
            with pytest.raises(ValidationError) as excinfo:
                Settings(_env_file=None, mt5_symbol="BTCUSD", **incomplete)
            message = str(excinfo.value)
            assert "BTCUSD profile requires explicitly configured values" in message

    def test_missing_entry_offset_is_named_in_the_error(self):
        with pytest.raises(ValidationError) as excinfo:
            Settings(_env_file=None, mt5_symbol="BTCUSD")
        assert "AUTO_TRADE_ENTRY_OFFSET" in str(excinfo.value)
        assert "AUTO_TRADE_LOT_SIZE" in str(excinfo.value)

    def test_explicit_profile_loads_and_syncs_the_symbol(self):
        settings = Settings(_env_file=None, **BTC_SETTINGS)

        assert settings.mt5_symbol == "BTCUSD"
        assert settings.auto_trade_symbol == "BTCUSD"
        assert settings.auto_trade_entry_offset == 50.0
        assert settings.auto_trade_timeframe == "M1"

    def test_auto_trade_symbol_alone_selects_the_instrument(self):
        settings = Settings(
            _env_file=None,
            auto_trade_symbol="BTCUSD",
            **{
                key: value
                for key, value in BTC_SETTINGS.items()
                if key != "mt5_symbol"
            },
        )
        assert settings.mt5_symbol == "BTCUSD"
        assert settings.auto_trade_symbol == "BTCUSD"

    def test_conflicting_symbol_configuration_is_rejected(self):
        with pytest.raises(ValidationError) as excinfo:
            Settings(_env_file=None, mt5_symbol="BTCUSD", auto_trade_symbol="XAUUSD")
        assert "different instruments" in str(excinfo.value)

    def test_xauusd_defaults_still_load_without_explicit_values(self):
        settings = Settings(_env_file=None)

        assert settings.mt5_symbol == "XAUUSD"
        # The effective instrument is mirrored into auto_trade_symbol.
        assert settings.auto_trade_symbol == "XAUUSD"
        # No BTCUSD-style requirement is imposed on the default profile.
        assert settings.auto_trade_entry_offset is None

    def test_timeframe_is_locked_to_m1(self):
        with pytest.raises(ValidationError) as excinfo:
            Settings(_env_file=None, mt5_symbol="BTCUSD", auto_trade_timeframe="M5", **{
                key: value
                for key, value in BTC_SETTINGS.items()
                if key != "mt5_symbol"
            })
        assert "M1" in str(excinfo.value)

    async def test_xauusd_values_do_not_leak_into_btcusd(self):
        fake = btc_fake()
        controller, _connection, _settings = await build_btc_controller(fake)

        assert controller._strategy_symbol == "BTCUSD"
        # The configured 50.00 offset applies; the XAUUSD 1.00 default does not.
        assert controller._entry_offset == 50.0
        await controller.start()
        await wait_for(lambda: controller._buy_entry is not None)
        assert controller._buy_entry == pytest.approx(BTC_REFERENCE + 50.0, abs=0.01)
        assert controller._sell_entry == pytest.approx(BTC_REFERENCE - 50.0, abs=0.01)
        assert controller._buy_sl == pytest.approx(BTC_REFERENCE, abs=0.01)
        await controller.stop()


# ======================================================================
# Symbol resolution and metadata
# ======================================================================
class TestBtcusdSymbolResolution:
    def test_discovery_resolves_a_broker_suffix_variant(self):
        fake = FakeMT5(
            symbols=[FakeSymbolInfo("BTCUSDm", digits=2, point=0.01)],
            ticks={"BTCUSDm": FakeTick(time=broker_time(), bid=104_000.0, ask=104_012.0)},
        )
        result = discover_symbol(
            fake, "BTCUSD", candidates=["BTCUSD", "BTCUSD.", "BTCUSDm"]
        )

        assert result.status is SymbolResolutionStatus.RESOLVED
        assert result.symbol == "BTCUSDm"
        assert result.resolved

    def test_discovery_never_falls_back_to_xauusd(self):
        fake = FakeMT5(symbols=[FakeSymbolInfo("XAUUSD")])
        result = discover_symbol(fake, "BTCUSD", candidates=["XAUUSD"])

        assert not result.resolved
        assert result.symbol is None
        assert result.status in (
            SymbolResolutionStatus.NOT_FOUND,
            SymbolResolutionStatus.AMBIGUOUS,
            SymbolResolutionStatus.UNAVAILABLE,
        )

    async def test_preflight_rejects_when_the_book_resolves_xauusd(self):
        fake = FakeMT5(
            symbols=[FakeSymbolInfo("XAUUSD")],
            ticks={"XAUUSD": FakeTick(time=broker_time(), bid=4185.0, ask=4186.0)},
        )
        controller, _connection, _settings = await build_btc_controller(fake)
        # A monitor that resolved the wrong instrument: preflight must refuse
        # it instead of trading whatever the terminal happens to offer.
        controller.monitor.symbol_status = SimpleNamespace(
            requested="BTCUSD", resolved="XAUUSD", resolution="resolved"
        )

        await controller.start()

        assert controller._status == "ERROR"
        assert "not a variant of BTCUSD" in (controller._last_error or "")
        assert not [call for call in fake.call_names() if call == "order_send"]

    async def test_preflight_blocks_when_the_symbol_cannot_be_resolved(self):
        fake = FakeMT5(symbols=[FakeSymbolInfo("BTCUSDm")])
        controller, _connection, _settings = await build_btc_controller(fake)
        controller.monitor.symbol_status = SimpleNamespace(
            requested="BTCUSD", resolved=None, resolution="not_found"
        )

        await controller.start()

        assert controller._status == "ERROR"
        assert "Symbol info is unavailable" in (controller._last_error or "")
        assert not [call for call in fake.call_names() if call == "order_send"]

    async def test_preflight_rejects_a_trading_disabled_symbol(self):
        fake = btc_fake(trade_mode=0)  # SYMBOL_TRADE_MODE_DISABLED
        controller, _connection, _settings = await build_btc_controller(fake)

        await controller.start()

        assert controller._status == "ERROR"
        assert "trading is disabled" in (controller._last_error or "")

    async def test_preflight_reports_the_resolved_broker_metadata(self, caplog):
        import logging

        caplog.set_level(logging.INFO, logger="app.services.auto_trading")
        fake = btc_fake()
        controller, _connection, _settings = await build_btc_controller(fake)

        await controller.start()

        assert controller._status == "RUNNING"
        metadata_lines = [
            record.getMessage()
            for record in caplog.records
            if "Resolved BTCUSD metadata" in record.getMessage()
        ]
        assert metadata_lines, "the resolved symbol metadata must be logged"
        assert "digits=2" in metadata_lines[0]
        assert "volume_min=0.01" in metadata_lines[0]

    async def test_stale_quotes_block_the_worker(self):
        fake = btc_fake()
        controller, _connection, _settings = await build_btc_controller(fake)
        controller.monitor.quote = SimpleNamespace(
            bid=104_000.0, ask=104_012.0, spread_points=500.0, is_stale=True
        )

        await controller.start()

        assert controller._status == "ERROR"
        assert "unavailable or stale" in (controller._last_error or "")

    async def test_volume_outside_broker_rules_blocks_start(self):
        fake = btc_fake(volume_min=0.1)
        controller, _connection, _settings = await build_btc_controller(fake)

        await controller.start()

        assert controller._status == "ERROR"
        assert "Volume below broker minimum" in (controller._last_error or "")


# ======================================================================
# Lifecycle on BTCUSD
# ======================================================================
class TestBtcusdLifecycle:
    async def test_pending_levels_use_the_configured_btcusd_offsets(self, monkeypatch):
        clock = VirtualClock()
        install_virtual_time(monkeypatch, clock)
        fake = btc_fake()
        controller, _connection, _settings = await build_btc_controller(fake)

        await controller.start()
        await _run_until_pending(controller, clock, fake)

        buy_stops = [order for order in fake.orders if order.type == 4]
        sell_stops = [order for order in fake.orders if order.type == 5]
        assert buy_stops and sell_stops
        assert buy_stops[0].price == pytest.approx(BTC_REFERENCE + 50.0, abs=0.01)
        assert buy_stops[0].sl == pytest.approx(BTC_REFERENCE, abs=0.01)
        assert sell_stops[0].price == pytest.approx(BTC_REFERENCE - 50.0, abs=0.01)
        assert sell_stops[0].sl == pytest.approx(BTC_REFERENCE, abs=0.01)
        # Both entries are pending stop orders on the configured symbol.
        assert buy_stops[0].symbol == "BTCUSD"
        await controller.stop()

    async def test_confirmed_sl_exit_switches_exactly_one_cycle(self, monkeypatch):
        clock = VirtualClock()
        install_virtual_time(monkeypatch, clock)
        fake = btc_fake()
        controller, _connection, _settings = await build_btc_controller(fake)

        await controller.start()
        await _run_until_pending(controller, clock, fake)
        buy_orders = [order for order in fake.orders if order.type == 4]
        assert buy_orders, "expected a Buy Stop"
        buy = buy_orders[0]
        fake.orders = [order for order in fake.orders if order.ticket != buy.ticket]
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
        assert controller._active_side == "buy"

        # The stop-loss is hit and MT5 publishes the confirmed deal.
        fake.positions = [p for p in fake.positions if p.ticket != position.ticket]
        fake.deals.append(
            FakeDeal(
                ticket=7100,
                position_id=position.ticket,
                position=position.ticket,
                price=controller._current_sl,
                profit=-25.0,
                comment="sl",
                reason=4,
                entry=1,
            )
        )
        await _run_until_pending(controller, clock, fake)

        assert controller._completed_cycles == 1
        assert len([order for order in fake.orders if order.type in (4, 5)]) == 2
        await controller.stop()

    async def test_trailing_uses_the_configured_btcusd_distance(self, monkeypatch):
        clock = VirtualClock()
        install_virtual_time(monkeypatch, clock)
        fake = btc_fake()
        controller, _connection, _settings = await build_btc_controller(fake)

        await controller.start()
        await _run_until_pending(controller, clock, fake)
        buy = [order for order in fake.orders if order.type == 4][0]
        fake.orders = [order for order in fake.orders if order.ticket != buy.ticket]
        position = FakePosition(
            ticket=7101,
            symbol="BTCUSD",
            magic=MAGIC,
            volume=0.05,
            price_open=controller._buy_entry,
            sl=controller._buy_sl,
            type=0,
        )
        fake.positions.append(position)
        await _run_until_pending(controller, clock, fake)

        # Drive the market above the break-even activation (entry + 25.00).
        # A long's favourable price is the bid, so the stop must trail at
        # (highest bid) - 15.00, in absolute BTCUSD units.
        best_bid = controller._buy_entry + 48.0
        controller.monitor.quote = SimpleNamespace(
            bid=best_bid,
            ask=best_bid + 12.0,
            spread_points=500.0,
            is_stale=False,
        )
        await _run_until_pending(controller, clock, fake, steps=30)

        assert controller._break_even_active is True
        assert position.sl == pytest.approx(best_bid - 15.0, abs=0.02)
        await controller.stop()

    async def test_a_saturday_quote_trades_like_any_other_day(self, monkeypatch):
        """No calendar gate exists: fresh Saturday quotes allow operation."""
        clock = VirtualClock()
        install_virtual_time(monkeypatch, clock)
        fake = btc_fake()
        # Stamp the fake tick on a UTC Saturday.
        now = datetime.now(timezone.utc)
        saturday = now + timedelta(days=(5 - now.weekday()) % 7)
        fake.ticks["BTCUSD"] = FakeTick(
            time=int(saturday.timestamp()) + DEFAULT_SERVER_OFFSET_SECONDS,
            bid=104_000.0,
            ask=104_012.0,
        )
        controller, _connection, _settings = await build_btc_controller(fake)

        await controller.start()
        await _run_until_pending(controller, clock, fake)

        assert controller._status == "RUNNING"
        assert [order for order in fake.orders if order.type in (4, 5)]
        await controller.stop()

    async def test_m1_timeframe_is_reported_unchanged(self):
        fake = btc_fake()
        controller, _connection, _settings = await build_btc_controller(fake)

        status = await controller.status()

        assert status.timeframe == "M1"
        assert status.symbol == "BTCUSD"

    async def test_m1_candle_end_does_not_close_a_position(self, monkeypatch):
        clock = VirtualClock()
        install_virtual_time(monkeypatch, clock)
        fake = btc_fake()
        controller, _connection, _settings = await build_btc_controller(fake)

        await controller.start()
        await _run_until_pending(controller, clock, fake)
        buy = [order for order in fake.orders if order.type == 4][0]
        fake.orders = [order for order in fake.orders if order.ticket != buy.ticket]
        position = FakePosition(
            ticket=7102,
            symbol="BTCUSD",
            magic=MAGIC,
            volume=0.05,
            price_open=controller._buy_entry,
            sl=controller._buy_sl,
            type=0,
        )
        fake.positions.append(position)
        # Many M1 candles pass while the position is open and untouched.
        for _ in range(12):
            clock.advance(60.0)
            await asyncio.sleep(0.01)
        await _run_until_pending(controller, clock, fake, steps=10)

        assert controller._active_side == "buy"
        assert position in fake.positions
        assert controller._completed_cycles == 0
        await controller.stop()
