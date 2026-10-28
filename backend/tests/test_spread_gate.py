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
