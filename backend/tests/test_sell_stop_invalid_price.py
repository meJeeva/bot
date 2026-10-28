"""Regression tests for ``SELL Stop rejected: retcode=10015 Invalid price``.

Confirmed against the real demo terminal: a SELL Stop is accepted only while
its price is at or below the current Bid, and a BUY Stop only while it is at
or above the current Ask. Anything else comes back from the broker as
``10015 Invalid price``. Everything here runs against the faked terminal; no
real order is placed.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from app.services.auto_trading import PHASE_WAITING_ENTRY, SIDE_SELL
from tests.auto_trading_harness import build_controller
from tests.fakes import (
    ORDER_TYPE_BUY_STOP,
    ORDER_TYPE_SELL_STOP,
    TRADE_ACTION_DEAL,
    TRADE_ACTION_PENDING,
    FakeMT5,
    FakeOrderResult,
    FakeSymbolInfo,
    FakeTick,
    broker_time,
    gold_terminal_with_live_tick,
)
from tests.test_side_specific_entry_offsets import _xauusd_overrides

# The configured cycle for this reference.
REFERENCE = 4030.92
BUY_ENTRY = 4031.39
BUY_SL = 4031.19
SELL_ENTRY = 4030.60
SELL_SL = 4030.80

# A market that has carried through the intended sell entry.
CROSSED_BID = 4030.40
CROSSED_ASK = 4030.44


def quote(bid: float, ask: float, *, point: float = 0.01) -> SimpleNamespace:
    return SimpleNamespace(
        bid=bid,
        ask=ask,
        point=point,
        spread_points=round((ask - bid) / point, 6),
        digits=2,
        is_stale=False,
    )


async def armed_controller(fake, *, stops_level: int = 0, **overrides):
    """A controller whose cycle is armed at the configured 4030.92 levels."""
    settings_overrides = {**_xauusd_overrides(), **overrides}
    controller, _connection, _settings = await build_controller(
        fake, **settings_overrides
    )
    controller.monitor.quote = quote(4030.90, 4030.94)
    await controller._preflight()
    controller._reference_value = REFERENCE
    controller._buy_entry = BUY_ENTRY
    controller._buy_sl = BUY_SL
    controller._sell_entry = SELL_ENTRY
    controller._sell_sl = SELL_SL
    controller._cycle_counter = 1
    controller._current_cycle_id = "session-1"
    controller._phase = PHASE_WAITING_ENTRY
    if stops_level:
        info = fake.symbol_info("XAUUSD")
        info.trade_stops_level = stops_level
    return controller


def submitted(fake, order_type: int | None = None) -> list[dict]:
    """Every pending-entry request the controller actually handed to MT5."""
    return [
        args[0]
        for name, args, _kwargs in fake.calls
        if name == "order_send" and args and isinstance(args[0], dict)
        if args[0].get("action") == TRADE_ACTION_PENDING
        if order_type is None or args[0].get("type") == order_type
    ]


def market_orders(fake) -> list[dict]:
    """Any request that would turn the entry into a market order."""
    return [
        args[0]
        for name, args, _kwargs in fake.calls
        if name == "order_send" and args and isinstance(args[0], dict)
        if args[0].get("action") == TRADE_ACTION_DEAL
    ]


def checked(fake, order_type: int | None = None) -> list[dict]:
    return [
        args[0]
        for name, args, _kwargs in fake.calls
        if name == "order_check" and args and isinstance(args[0], dict)
        if order_type is None or args[0].get("type") == order_type
    ]


def on_tick(price: float, tick_size: float) -> bool:
    steps = price / tick_size
    return abs(steps - round(steps)) < 1e-6


# ======================================================================
# 1. A valid SELL Stop, normalised to the broker's tick size
# ======================================================================
class TestTickSizeNormalisation:
    @pytest.mark.asyncio
    async def test_prices_are_normalised_to_tick_size_not_to_digits(self, monkeypatch):
        # digits=2 would keep 4031.37; SYMBOL_TRADE_TICK_SIZE=0.1 must not.
        fake = FakeMT5(
            symbols=[
                FakeSymbolInfo("XAUUSD", digits=2, point=0.01, trade_tick_size=0.1)
            ],
            ticks={"XAUUSD": FakeTick(time=broker_time(), bid=4030.90, ask=4030.94)},
        )
        controller, _connection, _settings = await build_controller(
            fake, **_xauusd_overrides()
        )
        controller.monitor.quote = quote(4030.90, 4030.94, point=0.01)
        await controller._preflight()
        await controller._initialize_cycle(controller.monitor.latest_quote())

        buy, sell = (
            submitted(fake, ORDER_TYPE_BUY_STOP)[0],
            submitted(fake, ORDER_TYPE_SELL_STOP)[0],
        )

        # 4030.92 + 0.47 = 4031.37, snapped to the 0.1 tick grid.
        assert buy["price"] == pytest.approx(4031.4)
        assert buy["sl"] == pytest.approx(4031.2)
        assert sell["price"] == pytest.approx(4030.6)
        assert sell["sl"] == pytest.approx(4030.8)
        assert not on_tick(4031.37, 0.1), "digits-only rounding must not win"

        for request in (buy, sell):
            assert on_tick(request["price"], 0.1)
            assert on_tick(request["sl"], 0.1)

        # order_check ran on the very same normalised request.
        checks = checked(fake, ORDER_TYPE_BUY_STOP)
        assert checks, "order_check must run before every submission"
        assert checks[0]["price"] == pytest.approx(4031.4)
        assert checks[0]["sl"] == pytest.approx(4031.2)

    @pytest.mark.asyncio
    async def test_a_valid_sell_stop_is_still_submitted(self, monkeypatch):
        fake = gold_terminal_with_live_tick(bid=4030.90, ask=4030.94)
        controller = await armed_controller(fake)

        submitted_ok = await controller._ensure_pending_order(
            SIDE_SELL, controller.monitor.latest_quote()
        )

        assert submitted_ok is True
        sell = submitted(fake, ORDER_TYPE_SELL_STOP)
        assert len(sell) == 1
        assert sell[0]["price"] == pytest.approx(SELL_ENTRY)
        assert sell[0]["sl"] == pytest.approx(SELL_SL)
        assert controller._sell_order_ticket is not None
        assert controller._failed_entries == 0


# ======================================================================
# 2. The configured entry / SL calculations are untouched
# ======================================================================
class TestConfiguredLevelsArePreserved:
    @pytest.mark.asyncio
    async def test_the_submitted_request_carries_the_exact_configured_levels(self):
        fake = gold_terminal_with_live_tick(bid=4030.90, ask=4030.94)
        controller, _connection, settings = await build_controller(
            fake, **_xauusd_overrides()
        )
        controller.monitor.quote = quote(4030.90, 4030.94)
        await controller._preflight()
        await controller._initialize_cycle(controller.monitor.latest_quote())

        assert controller._reference_value == REFERENCE
        assert controller._buy_entry == BUY_ENTRY
        assert controller._buy_sl == BUY_SL
        assert controller._sell_entry == SELL_ENTRY
        assert controller._sell_sl == SELL_SL

        buy = submitted(fake, ORDER_TYPE_BUY_STOP)[0]
        sell = submitted(fake, ORDER_TYPE_SELL_STOP)[0]
        assert (buy["price"], buy["sl"]) == (BUY_ENTRY, BUY_SL)
        assert (sell["price"], sell["sl"]) == (SELL_ENTRY, SELL_SL)

        # Nothing about the strategy distances changed.
        assert settings.auto_trade_buy_entry_offset == pytest.approx(0.47)
        assert settings.auto_trade_sell_entry_offset == pytest.approx(0.32)
        assert settings.auto_trade_initial_sl_distance == pytest.approx(0.20)
        assert settings.auto_trade_max_spread_points == 100

    def test_reference_4030_92_levels_are_unchanged(self):
        from app.strategy.range_break_even import build_cycle_levels

        levels = build_cycle_levels(
            REFERENCE,
            tick_size=0.01,
            digits=2,
            buy_entry_offset=0.47,
            sell_entry_offset=0.32,
            initial_sl_distance=0.20,
        )
        assert (levels.buy_entry, levels.buy_sl) == (BUY_ENTRY, BUY_SL)
        assert (levels.sell_entry, levels.sell_sl) == (SELL_ENTRY, SELL_SL)


# ======================================================================
# 3. The market moves between quote retrieval and submission
# ======================================================================
class TestPriceMovesBeforeSubmission:
    @pytest.mark.asyncio
    async def test_a_tick_that_moves_after_order_check_blocks_the_send(
        self, monkeypatch, caplog
    ):
        fake = gold_terminal_with_live_tick(bid=4030.90, ask=4030.94)
        controller = await armed_controller(fake)

        # The market drops through the sell entry while order_check runs.
        original_check = fake.order_check

        def moving_check(request):
            result = original_check(request)
            if request.get("type") == ORDER_TYPE_SELL_STOP:
                fake.ticks["XAUUSD"] = FakeTick(
                    time=broker_time(), bid=CROSSED_BID, ask=CROSSED_ASK
                )
            return result

        fake.order_check = moving_check

        with caplog.at_level(logging.WARNING, logger="app.services.auto_trading"):
            result = await controller._ensure_pending_order(
                SIDE_SELL, controller.monitor.latest_quote()
            )

        assert result is False
        assert submitted(fake, ORDER_TYPE_SELL_STOP) == []
        assert market_orders(fake) == []
        assert controller._last_entry_result and controller._last_entry_result.startswith(
            "ENTRY_MISSED SELL"
        )
        assert controller._failed_entries == 1
        assert controller._sell_order_ticket is None
        assert "ENTRY_MISSED SELL" in caplog.text

        # The entry is never silently moved and the spread limit never widens.
        assert controller._sell_entry == SELL_ENTRY
        assert controller._sell_sl == SELL_SL
        assert controller.settings.auto_trade_max_spread_points == 100

        # A fresh tick really was read after order_check and before any send.
        names = [name for name, _a, _k in fake.calls]
        assert "order_check" in names
        assert "symbol_info_tick" in names[names.index("order_check") + 1 :]


# ======================================================================
# 4. A SELL Stop that is on the wrong side of the market
# ======================================================================
class TestWrongSideOfTheMarket:
    @pytest.mark.asyncio
    async def test_a_crossed_sell_stop_is_never_sent(self, monkeypatch, caplog):
        fake = gold_terminal_with_live_tick(bid=CROSSED_BID, ask=CROSSED_ASK)
        controller = await armed_controller(fake)
        controller.monitor.quote = quote(CROSSED_BID, CROSSED_ASK)

        with caplog.at_level(logging.WARNING, logger="app.services.auto_trading"):
            result = await controller._ensure_pending_order(
                SIDE_SELL, controller.monitor.latest_quote()
            )

        assert result is False
        assert submitted(fake) == []
        assert checked(fake) == []
        assert "ENTRY_MISSED SELL" in caplog.text
        assert controller._last_entry_result.startswith("ENTRY_MISSED SELL")
        assert controller._failed_entries == 1
        # The cycle policy stays intact: no re-aiming, no market order.
        assert controller._sell_entry == SELL_ENTRY
        assert controller._sell_sl == SELL_SL
        assert controller._order_retry_at[SIDE_SELL] > 0

    @pytest.mark.asyncio
    async def test_the_same_happens_for_a_crossed_buy_stop(self):
        fake = gold_terminal_with_live_tick(bid=4031.90, ask=4031.94)
        controller = await armed_controller(fake)
        controller.monitor.quote = quote(4031.90, 4031.94)

        from app.services.auto_trading import SIDE_BUY

        result = await controller._ensure_pending_order(
            SIDE_BUY, controller.monitor.latest_quote()
        )

        assert result is False
        assert submitted(fake, ORDER_TYPE_BUY_STOP) == []
        assert controller._last_entry_result.startswith("ENTRY_MISSED BUY")
        assert controller._buy_entry == BUY_ENTRY


# ======================================================================
# 5. Broker minimum stop distance
# ======================================================================
class TestMinimumStopDistance:
    @pytest.mark.asyncio
    async def test_a_price_inside_the_broker_stop_level_is_never_sent(self, caplog):
        fake = gold_terminal_with_live_tick(bid=4030.75, ask=4030.79)
        # stops_level=20 points with point=0.01 -> 0.20 price units required.
        controller = await armed_controller(fake, stops_level=20)
        controller.monitor.quote = quote(4030.75, 4030.79)

        with caplog.at_level(logging.ERROR, logger="app.services.auto_trading"):
            result = await controller._ensure_pending_order(
                SIDE_SELL, controller.monitor.latest_quote()
            )

        assert result is False
        assert submitted(fake, ORDER_TYPE_SELL_STOP) == []
        # Not crossed: 4030.75 is still above the 4030.60 entry.
        assert "ENTRY_MISSED" not in (controller._last_entry_result or "")
        assert "broker requires 0.2" in (controller._last_error or "")
        assert "broker requires 0.2" in caplog.text
        assert controller._failed_entries == 1
        assert controller._order_retry_at[SIDE_SELL] > 0

    @pytest.mark.asyncio
    async def test_a_wide_enough_gap_still_submits(self):
        fake = gold_terminal_with_live_tick(bid=4031.00, ask=4031.04)
        controller = await armed_controller(fake, stops_level=20)
        controller.monitor.quote = quote(4031.00, 4031.04)

        result = await controller._ensure_pending_order(
            SIDE_SELL, controller.monitor.latest_quote()
        )

        assert result is True
        sell = submitted(fake, ORDER_TYPE_SELL_STOP)
        assert len(sell) == 1
        assert sell[0]["price"] == pytest.approx(SELL_ENTRY)


# ======================================================================
# 6. Duplicate prevention when the broker response is delayed
# ======================================================================
class TestDelayedBrokerResponse:
    @pytest.mark.asyncio
    async def test_a_late_rejection_never_produces_a_second_order(self):
        fake = gold_terminal_with_live_tick(bid=4030.90, ask=4030.94)
        controller = await armed_controller(fake)

        original_send = fake.order_send
        state = {"calls": 0}

        def delayed_response(request):
            # The broker really did accept the order; the client only ever
            # sees a stale "Invalid price" reply.
            result = original_send(request)
            if request.get("type") == ORDER_TYPE_SELL_STOP and state["calls"] == 0:
                state["calls"] += 1
                return FakeOrderResult(
                    retcode=10015,
                    comment="Invalid price",
                    order=result.order,
                    deal=0,
                    position=None,
                )
            return result

        fake.order_send = delayed_response

        result = await controller._ensure_pending_order(
            SIDE_SELL, controller.monitor.latest_quote()
        )

        assert result is True
        assert len(submitted(fake, ORDER_TYPE_SELL_STOP)) == 1
        sell_orders = [o for o in fake.orders if o.type == ORDER_TYPE_SELL_STOP]
        assert len(sell_orders) == 1
        assert controller._sell_order_ticket == sell_orders[0].ticket
        assert controller._failed_entries == 0
        assert "ENTRY_MISSED" not in (controller._last_entry_result or "")

    @pytest.mark.asyncio
    async def test_reconciliation_runs_before_a_price_rejection_is_retried(self):
        fake = gold_terminal_with_live_tick(bid=4030.90, ask=4030.94)
        controller = await armed_controller(fake)

        original_send = fake.order_send
        state = {"calls": 0}

        def reject_once(request):
            state["calls"] += 1
            if request.get("type") == ORDER_TYPE_SELL_STOP and state["calls"] == 1:
                return FakeOrderResult(retcode=10015, comment="Invalid price")
            return original_send(request)

        fake.order_send = reject_once
        names_before = len(fake.call_names())

        result = await controller._ensure_pending_order(
            SIDE_SELL, controller.monitor.latest_quote()
        )

        names_after = fake.call_names()[names_before:]
        assert "positions_get" in names_after
        assert "orders_get" in names_after
        # Retried only because a fresh tick still put the level on the valid side.
        assert result is True
        assert state["calls"] == 2, "exactly one bounded retry after the rejection"
        assert len([o for o in fake.orders if o.type == ORDER_TYPE_SELL_STOP]) == 1