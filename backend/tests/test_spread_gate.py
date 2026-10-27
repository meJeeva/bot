"""Spread gate: units, limits and blocked-entry behaviour.

The gate compares ``(ask - bid) / SYMBOL_POINT`` (spread in points) with
``auto_trade_max_spread_points`` (also points). These tests cover both sides of
that comparison, the symbol point sizes involved, invalid/missing quotes, the
BTCUSD profile, and the promise that no entry is submitted while the spread is
above the limit. Every terminal interaction goes through the mocked adapter in
``tests.fakes``; no real order is ever placed.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.mt5.connection import MT5Connection
from app.services.auto_trading import (
    PHASE_SPREAD_BLOCKED,
    PHASE_WAITING_ENTRY,
    SPREAD_BLOCKED,
    SPREAD_OK,
    SPREAD_UNAVAILABLE,
    AutoTradingController,
)
from tests.auto_trading_harness import (
    FakeMonitor,
    VirtualClock,
    build_controller,
    install_virtual_time,
)
from tests.fakes import FakeMT5, FakeSymbolInfo, FakeTick, broker_time

TRADE_ACTION_PENDING = 5
TRADE_ACTION_REMOVE = 8

BTC_SETTINGS = dict(
    mt5_symbol="BTCUSD",
    auto_trade_entry_offset=15.0,
    auto_trade_break_even_offset=4.0,
    auto_trade_trailing_distance=4.0,
    auto_trade_lot_size=1.0,
    auto_trade_max_spread_points=100.0,
)


def quote(bid, ask, *, point=0.01, digits=2, spread_points=None):
    """A minimal quote surface, with the symbol point the gate must use."""
    return SimpleNamespace(
        bid=bid,
        ask=ask,
        point=point,
        digits=digits,
        spread_points=spread_points,
        is_stale=False,
    )


def xau_controller(**overrides) -> AutoTradingController:
    """A controller for the default XAUUSD profile (limit 100 points)."""
    overrides.setdefault("database_enabled", False)
    settings = Settings(_env_file=None, **overrides)
    connection = MT5Connection(settings, mt5_module=FakeMT5())
    return AutoTradingController(settings, connection, FakeMonitor())


def btc_fake(*, point: float = 0.01, digits: int = 2) -> FakeMT5:
    """A terminal offering only the broker's BTCUSD.m suffix variant."""
    info = FakeSymbolInfo(
        "BTCUSD.m",
        digits=digits,
        point=point,
        trade_tick_size=point,
        volume_min=0.01,
        volume_max=50.0,
        volume_step=0.01,
        spread=1200,
    )
    return FakeMT5(
        symbols=[info],
        ticks={"BTCUSD.m": FakeTick(time=broker_time(), bid=104_000.0, ask=104_012.0)},
    )


async def build_btc_controller(fake: FakeMT5 | None = None, **overrides):
    """A started-capable BTCUSD controller over the BTCUSD.m broker symbol."""
    fake = fake or btc_fake()
    controller, connection, settings = await build_controller(
        fake, **{**BTC_SETTINGS, **overrides}
    )
    controller.monitor = FakeMonitor(symbol="BTCUSD.m", spread_points=1200.0)
    controller.monitor.quote = SimpleNamespace(
        bid=104_000.0, ask=104_012.0, spread_points=1200.0, is_stale=False
    )
    return controller, connection, settings, fake


def entry_requests(fake: FakeMT5) -> list[dict]:
    """Every pending-order submission the controller attempted."""
    return [
        request
        for name, args, _kwargs in fake.calls
        if name == "order_send"
        for request in (args[0] if args else {})
        if isinstance(request, dict) and request.get("action") == TRADE_ACTION_PENDING
    ]


async def advance(controller, clock: VirtualClock, steps: int = 20) -> None:
    for _ in range(steps):
        clock.advance(0.2)
        await asyncio.sleep(0.02)


# ======================================================================
# Units and limit boundaries
# ======================================================================
class TestSpreadUnitsAndLimits:
    def test_spread_below_the_limit_is_allowed(self):
        controller = xau_controller()

        check = controller._measure_spread(quote(4185.58, 4186.14))

        assert check.outcome == SPREAD_OK
        assert check.spread_price == pytest.approx(0.56)
        assert check.spread_points == pytest.approx(56.0)
        assert check.limit == 100.0
        assert not check.blocked

    def test_spread_equal_to_the_limit_is_allowed(self):
        controller = xau_controller()

        check = controller._measure_spread(quote(4185.00, 4186.00))

        assert check.spread_points == pytest.approx(100.0)
        assert check.outcome == SPREAD_OK
        assert not check.blocked

    def test_spread_above_the_limit_is_blocked(self):
        controller = xau_controller()

        check = controller._measure_spread(quote(4185.00, 4186.01))

        assert check.spread_points == pytest.approx(101.0)
        assert check.outcome == SPREAD_BLOCKED
        assert check.blocked
        assert "Spread exceeds maximum" in check.reason()
        assert "101 points > 100 configured" in check.reason()

    @pytest.mark.parametrize(
        ("point", "digits", "bid", "ask", "expected_points"),
        [
            # 5-digit FX: 3 pips is 30 points.
            (0.00001, 5, 1.10000, 1.10030, 30.0),
            # 2-digit metals/index: 0.56 of price is 56 points.
            (0.01, 2, 4185.58, 4186.14, 56.0),
            # Coarser point sizes stay in the same unit.
            (0.1, 1, 2400.0, 2400.5, 5.0),
            (1.0, 0, 100, 130, 30.0),
        ],
    )
    def test_different_symbol_point_sizes_use_the_same_points_unit(
        self, point, digits, bid, ask, expected_points
    ):
        controller = xau_controller()

        check = controller._measure_spread(
            quote(bid, ask, point=point, digits=digits)
        )

        assert check.point == point
        assert check.digits == digits
        assert check.spread_points == pytest.approx(expected_points)
        assert check.outcome == SPREAD_OK

    def test_price_difference_is_never_compared_with_the_points_limit(self):
        """A 0.56 price difference must not be read as 0.56 points."""
        controller = xau_controller()

        # 0.56 absolute price difference far exceeds a 0.1-point limit, but in
        # points it is 56, which is inside the 100-point limit.
        controller.settings.auto_trade_max_spread_points = 0.1
        check = controller._measure_spread(quote(4185.58, 4186.14))

        assert check.spread_points == pytest.approx(56.0)
        assert check.blocked

    def test_the_quote_spread_points_field_is_cross_checked(self, caplog):
        import logging

        caplog.set_level(logging.WARNING, logger="app.services.auto_trading")
        controller = xau_controller()

        # A quote that carries the price difference in `spread_points` (the
        # classic unit bug) must not drive the comparison.
        check = controller._measure_spread(
            quote(4185.58, 4186.14, spread_points=0.56)
        )

        assert check.spread_points == pytest.approx(56.0)
        assert check.outcome == SPREAD_OK
        assert "Spread unit mismatch" in caplog.text


# ======================================================================
# Unavailable quotes are reported separately from a genuine high spread
# ======================================================================
class TestUnavailableQuotes:
    @pytest.mark.parametrize(
        ("candidate", "detail"),
        [
            (None, "no quote is available"),
            (quote(None, 4186.14), "bid/ask are incomplete"),
            (quote(4185.58, None), "bid/ask are incomplete"),
            (quote(0, 4186.14), "bid/ask are not positive"),
            (quote("not-a-price", 4186.14), "bid/ask are not numeric"),
            (quote(4186.14, 4185.58), "ask is below bid"),
            (quote(4185.58, 4186.14, point=0), "symbol point size is invalid"),
            (quote(4185.58, 4186.14, point=None), "symbol point size is invalid"),
        ],
    )
    def test_invalid_or_missing_quotes_are_unavailable(self, candidate, detail):
        controller = xau_controller()

        check = controller._measure_spread(candidate)

        assert check.outcome == SPREAD_UNAVAILABLE
        assert check.unavailable
        assert detail in (check.detail or "")
        assert "Spread cannot be verified" in check.reason()
        # An invalid spread is never reported as a high-spread rejection.
        assert "exceeds maximum" not in check.reason()

    def test_missing_configured_limit_is_unavailable_not_blocked(self):
        controller = xau_controller(database_enabled=False)
        controller.settings.auto_trade_max_spread_points = None

        check = controller._measure_spread(quote(4185.58, 4186.14))

        assert check.outcome == SPREAD_UNAVAILABLE
        assert "maximum spread is unavailable" in (check.detail or "")


# ======================================================================
# BTCUSD profile resolution
# ======================================================================
class TestBtcusdSpreadProfile:
    async def test_btcusd_profile_resolves_and_measures_the_broker_symbol(self):
        controller, _connection, settings, _fake = await build_btc_controller()

        assert settings.auto_trade_profile == "BTCUSD"
        assert settings.auto_trade_symbol == "BTCUSD"
        check = controller._measure_spread(quote(104_000.0, 104_012.0))

        # The broker's suffix variant is the measured instrument, and the
        # profile's own 100-point limit is the one applied.
        assert controller._resolved_symbol() == "BTCUSD.m"
        assert check.symbol == "BTCUSD.m"
        assert check.profile == "BTCUSD"
        assert check.limit == 100.0
        assert check.spread_price == pytest.approx(12.0)
        assert check.spread_points == pytest.approx(1200.0)
        assert check.blocked

    async def test_btcusd_cents_style_point_size_scales_the_points(self):
        """A 2-digit BTCUSD with point 0.01 reports whole dollars as points."""
        fake = btc_fake(point=0.01, digits=2)
        controller, _connection, _settings, _fake = await build_btc_controller(fake)
        controller._tick_size = 0.01
        controller._digits = 2

        check = controller._measure_spread(
            SimpleNamespace(bid=104_000.0, ask=104_012.0, is_stale=False)
        )

        assert check.spread_points == pytest.approx(1200.0)
        assert check.point == 0.01
        assert check.digits == 2

    async def test_a_wider_limit_accepts_the_same_quote(self):
        controller, _connection, _settings, _fake = await build_btc_controller(
            auto_trade_max_spread_points=2000.0
        )

        check = controller._measure_spread(quote(104_000.0, 104_012.0))

        assert check.outcome == SPREAD_OK
        assert check.spread_points == pytest.approx(1200.0)
        assert check.limit == 2000.0


# ======================================================================
# Blocked entry is not a fatal strategy error
# ======================================================================
class TestBlockedEntryState:
    async def test_start_reports_a_blocked_entry_instead_of_error(self):
        controller, _connection, _settings, fake = await build_btc_controller()

        status = await controller.start()

        assert status.status == "RUNNING"
        assert status.strategy_phase == PHASE_SPREAD_BLOCKED
        assert status.spread_blocked is True
        assert status.spread_points == pytest.approx(1200.0)
        assert status.max_spread_points == 100.0
        assert status.profile == "BTCUSD"
        assert status.symbol == "BTCUSD.m"
        assert "Spread exceeds maximum" in (status.last_error or "")
        assert "1200 points > 100 configured" in (status.last_error or "")
        assert "BTCUSD.m" in (status.last_error or "")
        assert "profile=BTCUSD" in (status.last_error or "")
        # Nothing was submitted and no cycle reference was created.
        assert entry_requests(fake) == []
        assert controller._cycle_counter == 0
        assert controller._reference_value is None
        await controller.stop()

    async def test_no_entry_is_submitted_while_the_spread_exceeds_the_limit(
        self, monkeypatch
    ):
        clock = VirtualClock()
        install_virtual_time(monkeypatch, clock)
        controller, _connection, _settings, fake = await build_btc_controller()

        await controller.start()
        await advance(controller, clock, steps=25)

        assert controller._status == "RUNNING"
        assert controller._phase == PHASE_SPREAD_BLOCKED
        assert entry_requests(fake) == []
        assert fake.orders == []
        assert controller._cycle_counter == 0
        await controller.stop()

    async def test_ensure_pending_order_refuses_a_wide_spread(self):
        controller, _connection, _settings, fake = await build_btc_controller()
        controller._session_id = "session"
        controller._cycle_counter = 1
        controller._current_cycle_id = "session-1"
        controller._reference_value = 104_006.0
        controller._buy_entry = 104_021.0
        controller._buy_sl = 104_006.0
        controller._tick_size = 0.01
        controller._digits = 2

        submitted = await controller._ensure_pending_order(
            "buy", controller.monitor.latest_quote()
        )

        assert submitted is False
        assert entry_requests(fake) == []
        assert "Spread exceeds maximum" in (controller._last_error or "")

    async def test_fatal_errors_keep_their_own_status(self):
        """A non-spread failure must still fail loudly, not become 'blocked'."""
        fake = btc_fake()
        controller, _connection, _settings, _fake = await build_btc_controller(fake)
        controller.monitor.quote = SimpleNamespace(
            bid=104_000.0, ask=104_012.0, spread_points=1200.0, is_stale=True
        )

        status = await controller.start()

        assert status.status == "ERROR"
        assert status.strategy_phase == "ERROR"
        assert status.spread_blocked is False
        assert "unavailable or stale" in (status.last_error or "")


# ======================================================================
# Safe resume
# ======================================================================
class TestSpreadResume:
    async def test_a_quote_back_inside_the_limit_resumes_the_same_cycle(self, monkeypatch):
        clock = VirtualClock()
        install_virtual_time(monkeypatch, clock)
        controller, _connection, _settings, fake = await build_btc_controller()
        await controller.start()
        await advance(controller, clock, steps=5)
        assert controller._phase == PHASE_SPREAD_BLOCKED
        assert controller._cycle_counter == 0

        # Exactly at the limit: 100 points is inside the configured maximum.
        controller.monitor.quote = SimpleNamespace(
            bid=104_000.0, ask=104_001.0, spread_points=100.0, is_stale=False
        )
        await advance(controller, clock, steps=20)

        assert controller._phase == PHASE_WAITING_ENTRY
        assert controller._spread_blocked is False
        assert controller._last_error is None
        assert controller._cycle_counter == 1
        assert len(fake.orders) == 2
        assert {order.type for order in fake.orders} == {4, 5}
        # The cycle is built from the resumed quote's mid price (104_000.50),
        # not from the quote that was rejected while the spread was wide.
        assert controller._buy_entry == pytest.approx(104_000.5 + 15.0, abs=0.01)
        assert controller._sell_entry == pytest.approx(104_000.5 - 15.0, abs=0.01)

        # Further ticks must not duplicate the pending entries.
        await advance(controller, clock, steps=10)
        assert len(fake.orders) == 2
        assert controller._cycle_counter == 1
        await controller.stop()

    async def test_blocking_again_keeps_an_existing_cycle_reference(self, monkeypatch):
        clock = VirtualClock()
        install_virtual_time(monkeypatch, clock)
        controller, _connection, _settings, fake = await build_btc_controller()
        await controller.start()
        controller.monitor.quote = SimpleNamespace(
            bid=104_000.0, ask=104_001.0, spread_points=100.0, is_stale=False
        )
        await advance(controller, clock, steps=20)
        reference = controller._reference_value
        cycle_id = controller._current_cycle_id

        # The spread widens again while the entries are already armed, without
        # touching either entry level: the cycle keeps its reference and its
        # live pending orders.
        controller.monitor.quote = SimpleNamespace(
            bid=103_990.0, ask=104_010.0, spread_points=2000.0, is_stale=False
        )
        await advance(controller, clock, steps=5)

        assert controller._spread_blocked is True
        assert controller._phase == PHASE_WAITING_ENTRY
        assert controller._reference_value == reference
        assert controller._current_cycle_id == cycle_id
        assert len(fake.orders) == 2
        await controller.stop()
