"""Risk-engine assessment and account-level limit tests.

Every blocked scenario must produce an explicit machine-readable reason and
``allowed=False`` - a rejection is data, never an exception, and never a
silent zero that could authorize.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config import Settings
from app.execution.risk import (
    DailyRiskSnapshot,
    ExposureSnapshot,
    RiskEngine,
    RiskStateTracker,
    SymbolSpec,
    TradeIntent,
)
from app.schemas.market import Quote
from app.storage import StatusStore

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
CONTRACT = 100.0


def make_settings(**overrides) -> Settings:
    return Settings(**overrides)


def make_spec(**overrides) -> SymbolSpec:
    base = dict(
        name="XAUUSD",
        digits=2,
        point=0.01,
        trade_mode=4,
        contract_size=CONTRACT,
        tick_size=0.01,
        tick_value_loss=1.0,
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
    move = (exit_price - entry) if direction == "buy" else (entry - exit_price)
    return move * CONTRACT * volume


def broker_margin(symbol, direction, volume, price):
    return price * CONTRACT * volume / 100.0


def make_quote(**overrides) -> Quote:
    base = dict(
        symbol="XAUUSD",
        bid=4000.00,
        ask=4000.50,
        spread_points=50.0,
        point=0.01,
        digits=2,
        age_seconds=1.0,
        freshness="live",
        is_stale=False,
        server_time_offset_seconds=10800,
    )
    base.update(overrides)
    return Quote(**base)


def make_intent(**overrides) -> TradeIntent:
    base = dict(
        setup_id="setup-001",
        symbol="XAUUSD",
        timeframe="M15",
        direction="buy",
        zone_lower=3999.0,
        zone_upper=4001.0,
        primary_level_price=4000.0,
        stop_loss=3998.0,
        signal_time_utc=NOW - timedelta(minutes=5),
        confirmation_time_utc=NOW - timedelta(minutes=1),
        source="live_strategy",
    )
    base.update(overrides)
    return TradeIntent(**base)


def make_daily(**overrides) -> DailyRiskSnapshot:
    base = dict(
        risk_date="2026-01-15",
        baseline_equity=10_000.0,
        current_equity=10_000.0,
        daily_loss=0.0,
        daily_loss_limit=500.0,
        high_water_equity=10_000.0,
        drawdown=0.0,
        drawdown_limit=1_000.0,
        consecutive_losses=0,
        lockout_reason=None,
        baseline_available=True,
    )
    base.update(overrides)
    return DailyRiskSnapshot(**base)


def assess(
    intent: TradeIntent | None = None,
    *,
    settings: Settings | None = None,
    equity: float = 10_000.0,
    currency: str | None = "USD",
    margin_free: float = 10_000.0,
    symbol: SymbolSpec | None = None,
    quote: Quote | None = None,
    exposure: ExposureSnapshot | None = None,
    daily: DailyRiskSnapshot | None = None,
    calc_profit=broker_profit,
    calc_margin=broker_margin,
):
    engine = RiskEngine(settings or make_settings())
    return engine.assess(
        intent or make_intent(),
        account_equity=equity,
        account_currency=currency,
        account_margin_free=margin_free,
        symbol=symbol or make_spec(),
        quote=make_quote() if quote is None else quote,
        exposure=exposure or ExposureSnapshot(),
        daily=daily or make_daily(),
        calc_profit=calc_profit,
        calc_margin=calc_margin,
        now=NOW,
    )


class TestHappyPath:
    def test_valid_buy_is_allowed_with_hand_calculated_numbers(self):
        result = assess()
        # budget = 10000 * 0.5% = $50; entry = ask 4000.50; stop 3998.00
        # distance = 2.50 -> loss/lot = $250 -> volume = 0.20 -> loss = $50
        assert result.allowed is True, result.reasons
        assert result.reasons == []
        assert result.risk_budget == pytest.approx(50.0)
        assert result.entry_price == pytest.approx(4000.50)
        assert result.stop_loss == pytest.approx(3998.0)
        assert result.proposed_volume == pytest.approx(0.20)
        assert result.estimated_loss == pytest.approx(50.0)
        assert result.estimated_loss <= result.risk_budget
        assert result.stop_distance_points == pytest.approx(250.0)
        assert result.take_profit is None  # default policy: SL only
        assert result.source == "live_strategy"
        assert result.config_fingerprint

    def test_sell_enters_on_the_bid(self):
        intent = make_intent(direction="sell", stop_loss=4003.0)
        result = assess(intent)
        # entry = bid 4000.00; stop 4003.00 -> distance 3.00 -> loss/lot $300
        # volume = floor(50/300) = 0.16 -> loss $48
        assert result.allowed is True, result.reasons
        assert result.entry_price == pytest.approx(4000.0)
        assert result.proposed_volume == pytest.approx(0.16)
        assert result.estimated_loss == pytest.approx(48.0)

    def test_budget_breakdown_shows_the_most_restrictive_limit(self):
        result = assess()
        assert set(result.budget_breakdown) >= {
            "per_trade_cap",
            "aggregate_remaining",
            "daily_remaining",
        }
        assert result.budget_breakdown["per_trade_cap"] == pytest.approx(50.0)
        assert result.risk_budget == pytest.approx(50.0)

    def test_fixed_rr_take_profit_policy_is_applied_and_measured(self):
        settings = make_settings(execution_tp_policy="fixed_rr", execution_fixed_rr=2.0)
        result = assess(settings=settings)
        # entry 4000.50, risk 2.50, RR 2 -> tp = 4005.50
        assert result.allowed is True, result.reasons
        assert result.take_profit == pytest.approx(4005.50)
        assert result.reward_risk_ratio == pytest.approx(2.0, abs=0.01)


class TestSignalValidation:
    def test_replay_sourced_signals_are_rejected_by_the_risk_engine(self):
        result = assess(make_intent(source="replay"))
        assert result.allowed is False
        assert "signal_not_live_strategy" in result.reasons
        assert result.proposed_volume is None  # no sizing for a rejected signal

    @pytest.mark.parametrize("symbol", ["XAUEUR", "BTCUSD"])
    def test_symbols_outside_the_allow_list_are_rejected(self, symbol):
        result = assess(make_intent(symbol=symbol))
        assert "symbol_not_allowed" in result.reasons
        assert result.allowed is False

    def test_timeframes_outside_the_allow_list_are_rejected(self):
        result = assess(make_intent(timeframe="W1"))
        assert "timeframe_not_allowed" in result.reasons

    def test_stale_confirmation_is_rejected(self):
        intent = make_intent(confirmation_time_utc=NOW - timedelta(minutes=61))
        result = assess(intent)
        assert "signal_too_old" in result.reasons

    def test_future_confirmation_timestamp_is_rejected(self):
        intent = make_intent(confirmation_time_utc=NOW + timedelta(minutes=30))
        result = assess(intent)
        assert "confirmation_timestamp_invalid" in result.reasons

    def test_naive_confirmation_timestamp_is_rejected(self):
        intent = make_intent(
            confirmation_time_utc=NOW.replace(tzinfo=None),
            signal_time_utc=NOW.replace(tzinfo=None),
        )
        result = assess(intent)
        assert "confirmation_timestamp_invalid" in result.reasons


class TestQuoteChecks:
    def test_missing_quote_is_rejected(self):
        # The helper substitutes a healthy quote for None, so build the
        # engine directly to exercise the no-quote path.
        engine = RiskEngine(make_settings())
        result = engine.assess(
            make_intent(),
            account_equity=10_000.0,
            account_currency="USD",
            account_margin_free=10_000.0,
            symbol=make_spec(),
            quote=None,
            exposure=ExposureSnapshot(),
            daily=make_daily(),
            calc_profit=broker_profit,
            calc_margin=broker_margin,
            now=NOW,
        )
        assert result.allowed is False
        assert "quote_unavailable" in result.reasons

    def test_stale_quote_is_rejected(self):
        result = assess(quote=make_quote(is_stale=True, freshness="stale"))
        assert "quote_stale" in result.reasons

    def test_unknown_freshness_is_treated_as_not_live(self):
        result = assess(quote=make_quote(freshness="unknown"))
        assert "quote_stale" in result.reasons

    def test_old_quote_is_rejected(self):
        result = assess(quote=make_quote(age_seconds=30.0))
        assert "quote_too_old" in result.reasons

    def test_excessive_spread_is_rejected(self):
        result = assess(quote=make_quote(spread_points=500.0))
        assert "spread_too_high" in result.reasons

    def test_zero_bid_ask_is_rejected(self):
        result = assess(quote=make_quote(bid=0.0, ask=0.0, spread_points=0.0))
        assert "quote_invalid" in result.reasons

    def test_no_quote_at_all_never_authorizes(self):
        engine = RiskEngine(make_settings())
        result = engine.assess(
            make_intent(),
            account_equity=10_000.0,
            account_currency="USD",
            account_margin_free=10_000.0,
            symbol=make_spec(),
            quote=None,
            exposure=ExposureSnapshot(),
            daily=make_daily(),
            calc_profit=broker_profit,
            calc_margin=broker_margin,
            now=NOW,
        )
        assert result.allowed is False
        assert "quote_unavailable" in result.reasons


class TestStopValidation:
    def test_missing_stop_is_rejected(self):
        result = assess(make_intent(stop_loss=None))
        assert "stop_loss_missing" in result.reasons

    def test_buy_stop_above_entry_is_rejected(self):
        result = assess(make_intent(stop_loss=4005.0))
        assert "stop_loss_wrong_side" in result.reasons

    def test_sell_stop_below_entry_is_rejected(self):
        result = assess(make_intent(direction="sell", stop_loss=3995.0))
        assert "stop_loss_wrong_side" in result.reasons

    def test_stop_too_close_is_rejected(self):
        # 50 points < configured minimum of 100 points
        result = assess(make_intent(stop_loss=4000.00))
        assert "stop_too_close" in result.reasons or "stop_loss_wrong_side" in result.reasons

    def test_stop_too_far_is_rejected(self):
        # 60.00 price units = 6000 points > configured maximum 5000
        result = assess(make_intent(stop_loss=3940.00))
        assert "stop_too_far" in result.reasons

    def test_stop_not_tick_aligned_is_rejected(self):
        result = assess(make_intent(stop_loss=3998.005))
        assert "stop_not_tick_aligned" in result.reasons

    def test_broker_minimum_stop_distance_is_enforced(self):
        spec = make_spec(stops_level=300)  # broker requires >= 300 points
        result = assess(symbol=spec)       # configured stop is 250 points
        assert "broker_min_stop_distance" in result.reasons

    def test_price_drift_beyond_the_allowance_is_rejected(self):
        result = assess(make_intent(primary_level_price=4100.0))
        assert "price_drifted_beyond_entry" in result.reasons

    def test_missing_primary_level_is_rejected(self):
        result = assess(make_intent(primary_level_price=0.0))
        assert "primary_level_unavailable" in result.reasons


class TestAccountAndSymbolMetadata:
    @pytest.mark.parametrize(
        "mode,direction,expected",
        [
            (4, "buy", None),
            (0, "buy", "symbol_trading_disabled"),
            (3, "buy", "symbol_trading_disabled"),
            (None, "buy", "symbol_trading_disabled"),
            (1, "sell", "symbol_long_only"),
            (2, "buy", "symbol_short_only"),
        ],
    )
    def test_symbol_trade_mode_is_enforced(self, mode, direction, expected):
        result = assess(make_intent(direction=direction), symbol=make_spec(trade_mode=mode))
        if expected is None:
            assert result.allowed is True, result.reasons
        else:
            assert expected in result.reasons
            assert result.allowed is False

    def test_profit_currency_mismatch_is_rejected(self):
        result = assess(currency="EUR")
        assert "profit_currency_mismatch" in result.reasons

    def test_missing_account_currency_is_rejected(self):
        result = assess(currency=None)
        assert "account_currency_unavailable" in result.reasons

    def test_missing_contract_metadata_blocks_sizing(self):
        result = assess(symbol=make_spec(contract_size=None))
        assert "contract_size_invalid" in result.reasons
        assert result.proposed_volume is None

    def test_invalid_equity_is_rejected_not_treated_as_zero(self):
        result = assess(equity=float("nan"))
        assert "account_equity_unavailable" in result.reasons
        assert result.risk_budget is None


class TestAccountLevelLimits:
    def test_daily_lockout_blocks_new_entries(self):
        daily = make_daily(lockout_reason="daily_loss_lockout", daily_loss=500.0)
        result = assess(daily=daily)
        assert "daily_loss_lockout" in result.reasons
        assert result.allowed is False
        assert result.proposed_volume is None

    def test_drawdown_lockout_blocks_new_entries(self):
        result = assess(daily=make_daily(lockout_reason="drawdown_lockout"))
        assert "drawdown_lockout" in result.reasons

    def test_unavailable_daily_baseline_fails_closed(self):
        result = assess(daily=make_daily(baseline_available=False, baseline_equity=None))
        assert "daily_baseline_unavailable" in result.reasons

    def test_exhausted_daily_capacity_blocks(self):
        daily = make_daily(daily_loss=500.0, daily_loss_limit=500.0)
        result = assess(daily=daily)
        assert "daily_capacity_exhausted" in result.reasons

    def test_remaining_daily_capacity_caps_the_budget(self):
        daily = make_daily(daily_loss=450.0, daily_loss_limit=500.0)
        result = assess(daily=daily)
        # per-trade $50 but only $50 of daily capacity remains: min -> $50
        assert result.risk_budget == pytest.approx(50.0)

        daily = make_daily(daily_loss=480.0, daily_loss_limit=500.0)
        result = assess(daily=daily)
        assert result.risk_budget == pytest.approx(20.0)
        assert result.proposed_volume == pytest.approx(0.08)  # 20/250

    def test_consecutive_loss_circuit_breaker_blocks(self):
        settings = make_settings(execution_max_consecutive_losses=3)
        daily = make_daily(consecutive_losses=3)
        result = assess(settings=settings, daily=daily)
        assert "consecutive_losses_lockout" in result.reasons

    def test_aggregate_exposure_exhaustion_blocks(self):
        exposure = ExposureSnapshot(
            bot_positions=2, bot_open_risk=500.0
        )  # limit = 10000 * 5% = $500
        result = assess(exposure=exposure)
        assert "aggregate_risk_exhausted" in result.reasons
        assert result.allowed is False

    def test_aggregate_exposure_reduces_the_remaining_budget(self):
        exposure = ExposureSnapshot(bot_positions=1, bot_open_risk=475.0)
        result = assess(exposure=exposure)
        # $500 aggregate limit - $475 used = $25 remaining < $50 per-trade
        assert result.risk_budget == pytest.approx(25.0)
        assert result.proposed_volume == pytest.approx(0.10)  # 25/250 -> 0.10

    def test_max_open_positions_blocks(self):
        exposure = ExposureSnapshot(bot_positions=3, bot_open_risk=0.0)
        result = assess(exposure=exposure)
        assert "max_open_positions" in result.reasons

    def test_pending_orders_count_towards_position_limits(self):
        exposure = ExposureSnapshot(pending_bot_orders=3)
        result = assess(exposure=exposure)
        assert "max_open_positions" in result.reasons

    def test_bot_position_without_a_stop_blocks_new_entries(self):
        exposure = ExposureSnapshot(bot_positions=1, bot_positions_missing_stop=1)
        result = assess(exposure=exposure)
        assert "bot_position_missing_stop" in result.reasons

    def test_unresolved_exposure_blocks(self):
        result = assess(exposure=ExposureSnapshot(unresolved=True))
        assert "exposure_unresolved" in result.reasons

    def test_external_positions_block_only_when_policy_requires_it(self):
        default = assess(exposure=ExposureSnapshot(external_positions=2))
        assert "external_positions_present" not in default.reasons

        strict = make_settings(execution_block_on_external_positions=True)
        result = assess(
            settings=strict, exposure=ExposureSnapshot(external_positions=2)
        )
        assert "external_positions_present" in result.reasons


class TestRiskStateTracker:
    def _tracker(self, tmp_path, settings=None, name="risk.db"):
        store = StatusStore(tmp_path / name, enabled=True)
        assert store.initialize()
        return store, RiskStateTracker(store, settings or make_settings())

    def test_first_sync_establishes_the_daily_baseline(self, tmp_path):
        _, tracker = self._tracker(tmp_path)
        assert tracker.available is True

        tracker.sync(equity=10_000.0, balance=10_000.0, now=NOW, server_offset_seconds=10800)
        snap = tracker.snapshot(
            equity=10_000.0, daily_loss_limit_percent=5.0, drawdown_limit_percent=10.0
        )
        assert snap.baseline_available is True
        assert snap.baseline_equity == pytest.approx(10_000.0)
        assert snap.daily_loss == pytest.approx(0.0)
        assert snap.daily_loss_limit == pytest.approx(500.0)

    def test_daily_loss_counts_equity_decline(self, tmp_path):
        _, tracker = self._tracker(tmp_path)
        tracker.sync(equity=10_000.0, balance=10_000.0, now=NOW, server_offset_seconds=10800)

        snap = tracker.snapshot(
            equity=9_400.0, daily_loss_limit_percent=5.0, drawdown_limit_percent=10.0
        )
        assert snap.daily_loss == pytest.approx(600.0)
        assert snap.daily_loss > snap.daily_loss_limit  # over the limit

    def test_daily_loss_survives_a_restart(self, tmp_path):
        store, tracker = self._tracker(tmp_path)
        tracker.sync(equity=10_000.0, balance=10_000.0, now=NOW, server_offset_seconds=10800)
        tracker.set_lockout("daily_loss_lockout", NOW)
        store.close()

        # A fresh process opens the same database.
        store2 = StatusStore(tmp_path / "risk.db", enabled=True)
        assert store2.initialize()
        tracker2 = RiskStateTracker(store2, make_settings())

        assert tracker2.risk_date == "2026-01-15"
        assert tracker2.lockout_reason == "daily_loss_lockout"
        snap = tracker2.snapshot(
            equity=9_000.0, daily_loss_limit_percent=5.0, drawdown_limit_percent=10.0
        )
        assert snap.daily_loss == pytest.approx(1_000.0)  # baseline NOT reset
        store2.close()

    @pytest.mark.parametrize(
        "now,offset,expected",
        [
            (datetime(2026, 1, 15, 20, 59, 59, tzinfo=timezone.utc), 10800, "2026-01-15"),
            (datetime(2026, 1, 15, 21, 0, 0, tzinfo=timezone.utc), 10800, "2026-01-16"),
            (datetime(2026, 1, 15, 22, 0, 0, tzinfo=timezone.utc), 10800, "2026-01-16"),
            (datetime(2026, 1, 15, 23, 30, 0, tzinfo=timezone.utc), 0, "2026-01-15"),
        ],
    )
    def test_broker_midnight_boundary(self, tmp_path, now, offset, expected):
        _, tracker = self._tracker(tmp_path)
        assert tracker.risk_date_for(now, offset) == expected

    def test_utc_midnight_boundary(self, tmp_path):
        settings = make_settings(execution_daily_reset="utc_midnight")
        _, tracker = self._tracker(tmp_path, settings)
        # 20:59 UTC is already the next day at the broker but not in UTC.
        assert (
            tracker.risk_date_for(datetime(2026, 1, 15, 20, 59, tzinfo=timezone.utc), 10800)
            == "2026-01-15"
        )

    def test_rollover_resets_the_daily_window_but_keeps_the_high_water_mark(self, tmp_path):
        _, tracker = self._tracker(tmp_path)
        tracker.sync(equity=11_000.0, balance=11_000.0, now=NOW, server_offset_seconds=10800)
        tracker.set_lockout("daily_loss_lockout", NOW)
        tracker.record_consecutive_losses(4, NOW)

        next_day = NOW + timedelta(days=1)
        tracker.sync(equity=9_000.0, balance=9_000.0, now=next_day, server_offset_seconds=10800)

        assert tracker.risk_date == "2026-01-16"
        assert tracker.lockout_reason is None          # daily lockout cleared
        assert tracker.consecutive_losses == 0         # daily counter reset
        snap = tracker.snapshot(
            equity=9_000.0, daily_loss_limit_percent=5.0, drawdown_limit_percent=10.0
        )
        assert snap.high_water_equity == pytest.approx(11_000.0)  # HWM kept
        assert snap.baseline_equity == pytest.approx(9_000.0)     # new baseline

    def test_high_water_mark_only_moves_up(self, tmp_path):
        _, tracker = self._tracker(tmp_path)
        tracker.sync(equity=10_000.0, balance=10_000.0, now=NOW, server_offset_seconds=10800)
        tracker.sync(equity=12_000.0, balance=12_000.0, now=NOW, server_offset_seconds=10800)
        tracker.sync(equity=8_000.0, balance=8_000.0, now=NOW, server_offset_seconds=10800)

        snap = tracker.snapshot(
            equity=8_000.0, daily_loss_limit_percent=5.0, drawdown_limit_percent=10.0
        )
        assert snap.high_water_equity == pytest.approx(12_000.0)
        assert snap.drawdown == pytest.approx(4_000.0)
        assert snap.drawdown_limit == pytest.approx(1_200.0)

    def test_drawdown_lockout_survives_the_daily_rollover(self, tmp_path):
        _, tracker = self._tracker(tmp_path)
        tracker.sync(equity=10_000.0, balance=10_000.0, now=NOW, server_offset_seconds=10800)
        tracker.set_lockout("drawdown_lockout", NOW)

        tracker.sync(
            equity=10_000.0,
            balance=10_000.0,
            now=NOW + timedelta(days=1),
            server_offset_seconds=10800,
        )
        assert tracker.lockout_reason == "drawdown_lockout"

    def test_explicit_recovery_only_clears_allowed_reasons(self, tmp_path):
        _, tracker = self._tracker(tmp_path)
        tracker.sync(equity=10_000.0, balance=10_000.0, now=NOW, server_offset_seconds=10800)
        tracker.set_lockout("drawdown_lockout", NOW)

        # A daily-rollover-style recovery must not clear a drawdown lockout.
        assert tracker.clear_lockout(NOW, allowed=("daily_loss_lockout",)) is False
        assert tracker.lockout_reason == "drawdown_lockout"

        assert tracker.clear_lockout(NOW, allowed=("drawdown_lockout",)) is True
        assert tracker.lockout_reason is None

    def test_persistence_unavailable_fails_the_state_closed(self, tmp_path):
        tracker = RiskStateTracker(None, make_settings())
        assert tracker.available is False
        tracker.sync(
            equity=10_000.0, balance=10_000.0, now=NOW, server_offset_seconds=10800
        )
        snap = tracker.snapshot(
            equity=10_000.0, daily_loss_limit_percent=5.0, drawdown_limit_percent=10.0
        )
        assert snap.baseline_available is False
