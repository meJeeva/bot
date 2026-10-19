"""Position sizing - hand-calculated, independently verifiable.

Every expected number below is derived by hand from the documented formula,
*not* by calling the implementation twice:

    loss_per_lot = contract_size * |entry - stop| * volume      (broker P&L)
    volume       = floor(budget / loss_per_lot / step) * step   (round DOWN)
    est_loss     = loss_per_lot * volume      (recomputed after rounding)

The broker P&L fake mirrors ``mt5.order_calc_profit`` semantics verified live
against the real terminal (XAUUSD, contract 100: a $1 adverse move on 1.0 lot
= -$100).
"""

from __future__ import annotations

import math

import pytest

from app.execution.risk import SymbolSpec, floor_to_step, size_position

CONTRACT = 100.0  # XAUUSD contract size (verified live)


def make_spec(**overrides) -> SymbolSpec:
    base = dict(
        name="XAUUSD",
        digits=2,
        point=0.01,
        trade_mode=4,
        contract_size=CONTRACT,
        tick_size=0.01,
        tick_value_loss=0.1,  # deliberately inconsistent with the broker P&L
        currency_profit="USD",
        volume_step=0.01,
        volume_min=0.01,
        volume_max=100.0,
        volume_limit=0.0,
        stops_level=0,
        freeze_level=0,
        filling_mode=3,
    )
    base.update(overrides)
    return SymbolSpec(**base)


def broker_profit(symbol, direction, volume, entry, exit_price):
    """Signed account-currency P&L, exactly like order_calc_profit."""
    move = (exit_price - entry) if direction == "buy" else (entry - exit_price)
    return move * CONTRACT * volume


def broker_margin(symbol, direction, volume, price):
    """Mirror of order_calc_margin: price * contract * volume / leverage(100)."""
    return price * CONTRACT * volume / 100.0


def size(budget, *, entry=4000.0, stop=3998.0, direction="buy", **kwargs):
    return size_position(
        budget=budget,
        direction=direction,
        entry=entry,
        stop_loss=stop,
        spec=kwargs.pop("spec", make_spec()),
        calc_profit=kwargs.pop("calc_profit", broker_profit),
        calc_margin=kwargs.pop("calc_margin", broker_margin),
        margin_free=kwargs.pop("margin_free", 10_000.0),
        allowance_percent=kwargs.pop("allowance_percent", 0.0),
        take_profit=kwargs.pop("take_profit", None),
    )


class TestFloorToStep:
    @pytest.mark.parametrize(
        "value,step,expected",
        [
            (0.259, 0.01, 0.25),
            (1.0, 0.01, 1.0),
            (0.16666, 0.01, 0.16),
            (0.009, 0.01, 0.0),          # never rounds UP to the minimum
            (2.5, 0.5, 2.5),
            (2.7, 0.5, 2.5),
            (0.30000000000000004, 0.01, 0.3),  # float artifact tolerance
        ],
    )
    def test_rounds_down_to_the_step(self, value, step, expected):
        assert floor_to_step(value, step) == pytest.approx(expected)


class TestHandCalculatedSizing:
    def test_buy_with_two_dollar_stop(self):
        # budget = 10000 * 0.5% = $50; loss per lot = 100 * $2.00 = $200
        # volume = 50 / 200 = 0.25 lots (exactly on the 0.01 step)
        # estimated loss = 0.25 * 200 = $50 (equals the budget, never above)
        result, reasons, _ = size(50.0)
        assert reasons == []
        assert result is not None
        assert result.volume == pytest.approx(0.25)
        assert result.loss_per_lot == pytest.approx(200.0)
        assert result.estimated_loss == pytest.approx(50.0)
        assert result.estimated_loss <= 50.0 + 1e-9

    def test_rounding_floors_the_volume_and_recomputes_the_loss(self):
        # budget $50, loss/lot = 100 * 3.00 = $300
        # raw = 50/300 = 0.1666.. -> floor -> 0.16 -> loss = $48 (not $50)
        result, reasons, _ = size(50.0, entry=4000.0, stop=3997.0)
        assert reasons == []
        assert result is not None
        assert result.volume == pytest.approx(0.16)
        assert result.estimated_loss == pytest.approx(48.0)
        assert result.estimated_loss <= 50.0

    def test_smaller_equity_produces_a_smaller_volume(self):
        # budget = 2000 * 0.5% = $10 -> 10/200 = 0.05 lots
        result, reasons, _ = size(10.0)
        assert reasons == []
        assert result is not None
        assert result.volume == pytest.approx(0.05)
        assert result.estimated_loss == pytest.approx(10.0)

    def test_sell_side_uses_the_same_math_with_the_stop_above(self):
        # entry 4000, stop 4002 (sell): loss/lot = 100 * 2 = $200, budget $25
        result, reasons, _ = size(25.0, entry=4000.0, stop=4002.0, direction="sell")
        assert reasons == []
        assert result is not None
        assert result.volume == pytest.approx(0.12)  # floor(0.125)
        assert result.estimated_loss == pytest.approx(24.0)

    def test_cost_allowance_reduces_the_spendable_budget(self):
        # 10% allowance: effective = $45 -> 45/200 = 0.225 -> floor 0.22 -> $44
        result, reasons, _ = size(50.0, allowance_percent=10.0)
        assert reasons == []
        assert result is not None
        assert result.volume == pytest.approx(0.22)
        assert result.estimated_loss == pytest.approx(44.0)
        assert result.estimated_loss <= 45.0

    def test_maximum_broker_volume_clamps_a_large_budget(self):
        # budget $10,000 with a $200 loss/lot would allow 50 lots; the broker
        # maximum (1.0) must clamp it and the loss recomputed at 1.0 lot.
        spec = make_spec(volume_max=1.0)
        result, reasons, _ = size(10_000.0, spec=spec)
        assert reasons == []
        assert result is not None
        assert result.volume == pytest.approx(1.0)
        assert result.estimated_loss == pytest.approx(200.0)

    def test_minimum_volume_exceeding_the_budget_is_rejected(self):
        # budget $0.10 with a $200/lot stop would need 0.0005 lots < min 0.01
        result, reasons, _ = size(0.10)
        assert result is None
        assert "min_volume_exceeds_risk_budget" in reasons

    def test_broker_volume_limit_is_honoured(self):
        spec = make_spec(volume_limit=0.10)
        result, reasons, _ = size(10_000.0, spec=spec)
        assert reasons == []
        assert result is not None
        assert result.volume == pytest.approx(0.10)

    def test_inconsistent_broker_tick_value_does_not_oversize_the_trade(self):
        """The live broker reports tick_value 10x smaller than its own P&L.

        Tick math would claim $20/lot where the broker P&L says $200/lot -
        sizing must follow the broker P&L (0.25 lots) and disclose the
        inconsistency, never size 10x too large.
        """
        result, reasons, warnings = size(50.0)
        assert reasons == []
        assert result is not None
        assert result.volume == pytest.approx(0.25)  # NOT 2.5
        assert "tick_value_metadata_inconsistent_with_broker_pnl" in warnings

    def test_consistent_tick_metadata_produces_no_warning(self):
        spec = make_spec(tick_value_loss=1.0)  # matches contract 100 * 0.01
        result, _, warnings = size(50.0, spec=spec)
        assert result is not None
        assert "tick_value_metadata_inconsistent_with_broker_pnl" not in warnings


class TestUnreliableDataIsRejected:
    @pytest.mark.parametrize(
        "overrides,expected_reason",
        [
            ({"contract_size": None}, "contract_size_invalid"),
            ({"contract_size": float("nan")}, "contract_size_invalid"),
            ({"contract_size": 0.0}, "contract_size_invalid"),
            ({"tick_size": None}, "tick_size_invalid"),
            ({"volume_step": 0.0}, "volume_step_invalid"),
            ({"volume_step": None}, "volume_step_invalid"),
            ({"volume_min": -1.0}, "volume_min_invalid"),
            ({"volume_max": 0.0}, "volume_max_invalid"),
            ({"volume_min": 5.0, "volume_max": 1.0}, "volume_range_invalid"),
            ({"currency_profit": None}, "profit_currency_unavailable"),
            ({"currency_profit": "  "}, "profit_currency_unavailable"),
            ({"point": 0.0}, "point_invalid"),
        ],
    )
    def test_bad_symbol_metadata_blocks_sizing(self, overrides, expected_reason):
        result, reasons, _ = size(50.0, spec=make_spec(**overrides))
        assert result is None
        assert expected_reason in reasons

    @pytest.mark.parametrize("budget", [0.0, -10.0, float("nan"), float("inf")])
    def test_invalid_budget_is_rejected(self, budget):
        result, reasons, _ = size(budget)
        assert result is None
        assert reasons  # explicit, never a silent zero

    @pytest.mark.parametrize(
        "value,expected_reason",
        [
            (None, "loss_calculation_unavailable"),
            (float("nan"), "loss_calculation_unavailable"),
            (float("inf"), "loss_calculation_unavailable"),
            (0.0, "loss_calculation_unavailable"),
            # A broker that returns -5.0 regardless of volume produces a usable
            # loss_per_lot (5.0) from the per-lot check, but its own math does
            # not scale with volume; the loss re-evaluated at the selected
            # volume disagrees with loss_per_lot * volume. This is
            # "loss_calculation_inconsistent" (the same rejection exercised by
            # test_non_linear_broker_math_is_rejected_as_inconsistent), not
            # "loss_calculation_unavailable".
            (-5.0, "loss_calculation_inconsistent"),
        ],
    )
    def test_unusable_broker_loss_calculation_is_rejected(
        self, value, expected_reason
    ):
        def calc(symbol, direction, volume, entry, exit_price):
            return value

        result, reasons, _ = size(50.0, calc_profit=calc)
        assert result is None
        assert expected_reason in reasons

    def test_missing_profit_calculator_result_is_rejected(self):
        result, reasons, _ = size(50.0, calc_profit=lambda *a: None)
        assert result is None
        assert "loss_calculation_unavailable" in reasons

    def test_non_linear_broker_math_is_rejected_as_inconsistent(self):
        """A broker whose per-volume loss disagrees with its per-lot loss."""

        def nonlinear(symbol, direction, volume, entry, exit_price):
            loss = abs(entry - exit_price) * CONTRACT
            if volume >= 1.0:
                return -loss * volume
            return -(loss * volume) / 10.0  # 10x "cheaper" at small volumes

        result, reasons, _ = size(50.0, calc_profit=nonlinear)
        assert result is None
        assert "loss_calculation_inconsistent" in reasons

    def test_loss_rounding_that_exceeds_the_budget_is_rejected(self):
        """Defensive: broker returns a loss above the budget after rounding.

        A broker with a fixed per-order component that shrinks as volume grows
        keeps the per-volume result within the 5% consistency band while
        pushing the recomputed loss above the budget at the selected volume.
        """

        def creeping(symbol, direction, volume, entry, exit_price):
            base = abs(entry - exit_price) * CONTRACT  # 200 for default params
            # loss_per_lot = 201 at volume=1.0; at volume=0.24 the fixed
            # add-on inflates the loss to 50.52, which exceeds the $50 budget
            # but stays within 5% of 201*0.24 = 48.24 (2.28 / 48.24 = 4.7%).
            return -((base + 1.0) * volume + 3.0 * (1.0 - volume))

        result, reasons, _ = size(50.0, calc_profit=creeping)
        assert result is None
        assert "rounded_loss_exceeds_budget" in reasons

    def test_margin_above_free_margin_is_rejected(self):
        result, reasons, _ = size(50.0, margin_free=1.0)
        assert result is None
        assert "insufficient_margin" in reasons

    def test_unavailable_margin_is_a_warning_not_an_authorization(self):
        result, reasons, warnings = size(
            50.0, calc_margin=lambda *a: None
        )
        assert reasons == []
        assert result is not None
        assert "margin_estimate_unavailable" in warnings

    def test_invalid_entry_or_stop_is_rejected(self):
        result, reasons, _ = size(50.0, entry=float("nan"))
        assert result is None
        assert "entry_or_stop_invalid" in reasons


class TestTakeProfitReward:
    def test_reward_to_risk_is_reported_when_a_target_exists(self):
        # entry 4000, stop 3998 ($2 risk), tp 4004 ($4 reward) => RR 2.0
        result, reasons, warnings = size(50.0, take_profit=4004.0)
        assert reasons == []
        assert result is not None
        assert any(w.startswith("reward_risk_ratio:2") for w in warnings)

    def test_unavailable_reward_is_a_warning(self):
        def broken_reward(symbol, direction, volume, entry, exit_price):
            if exit_price > entry and direction == "buy":
                return None
            return broker_profit(symbol, direction, volume, entry, exit_price)

        result, reasons, warnings = size(
            50.0, take_profit=4004.0, calc_profit=broken_reward
        )
        assert reasons == []
        assert result is not None
        assert "take_profit_reward_unavailable" in warnings
