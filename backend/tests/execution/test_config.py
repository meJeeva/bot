"""Phase 4 configuration validation.

The safety model starts here: execution is disabled by default, enabling it
requires an explicit demo identity, and any inconsistent risk configuration
refuses to start the process instead of silently clamping.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def build(**overrides):
    return Settings(**overrides)


class TestDisabledByDefault:
    def test_execution_is_disabled_by_default(self):
        settings = build()
        assert settings.execution_enabled is False
        assert settings.execution_configured is False
        assert settings.execution_demo_login is None
        assert settings.execution_demo_server is None

    def test_defaults_keep_the_core_read_only(self):
        settings = build()
        assert settings.app_read_only is True

    def test_enabled_flag_alone_is_not_a_valid_configuration(self):
        with pytest.raises(ValidationError) as info:
            build(execution_enabled=True)
        messages = " ".join(str(e["msg"]) for e in info.value.errors())
        assert "EXECUTION_DEMO_LOGIN" in messages

    def test_enabled_flag_requires_a_server_too(self):
        with pytest.raises(ValidationError) as info:
            build(execution_enabled=True, execution_demo_login=12345)
        messages = " ".join(str(e["msg"]) for e in info.value.errors())
        assert "EXECUTION_DEMO_SERVER" in messages

    def test_full_demo_identity_is_accepted_and_marks_configuration_ready(self):
        settings = build(
            execution_enabled=True,
            execution_demo_login=12345,
            execution_demo_server="MetaQuotes-Demo",
        )
        assert settings.execution_enabled is True
        assert settings.execution_configured is True


class TestRiskConfigurationValidation:
    def test_default_risk_policy_is_conservative(self):
        settings = build()
        assert settings.execution_risk_per_trade_percent == 0.5
        assert settings.execution_max_daily_loss_percent == 5.0
        assert settings.execution_max_daily_drawdown_percent == 10.0

    def test_per_trade_risk_above_the_cap_is_rejected_not_clamped(self):
        with pytest.raises(ValidationError) as info:
            build(
                execution_risk_per_trade_percent=3.0,
                execution_max_risk_per_trade_percent=1.0,
            )
        messages = " ".join(str(e["msg"]) for e in info.value.errors())
        assert "EXECUTION_RISK_PER_TRADE_PERCENT" in messages

    def test_daily_loss_above_drawdown_is_rejected_as_inconsistent(self):
        with pytest.raises(ValidationError) as info:
            build(
                execution_max_daily_loss_percent=20.0,
                execution_max_daily_drawdown_percent=10.0,
            )
        messages = " ".join(str(e["msg"]) for e in info.value.errors())
        assert "EXECUTION_MAX_DAILY_LOSS_PERCENT" in messages

    def test_inverted_stop_distance_range_is_rejected(self):
        with pytest.raises(ValidationError) as info:
            build(
                execution_min_stop_distance_points=500.0,
                execution_max_stop_distance_points=100.0,
            )
        messages = " ".join(str(e["msg"]) for e in info.value.errors())
        assert "EXECUTION_MIN_STOP_DISTANCE_POINTS" in messages

    @pytest.mark.parametrize(
        "field,value",
        [
            ("execution_risk_per_trade_percent", 0.0),
            ("execution_risk_per_trade_percent", -1.0),
            ("execution_max_daily_loss_percent", 0.0),
            ("execution_max_quote_age_seconds", 0.0),
            ("execution_max_signal_age_minutes", -5.0),
            ("execution_cost_allowance_percent", -1.0),
            ("execution_fixed_rr", 0.0),
        ],
    )
    def test_non_positive_or_negative_limits_are_rejected(self, field, value):
        with pytest.raises(ValidationError):
            build(**{field: value})

    def test_nan_risk_percentage_is_rejected(self):
        with pytest.raises(ValidationError):
            build(execution_risk_per_trade_percent=float("nan"))

    def test_consecutive_loss_circuit_breaker_defaults_to_disabled(self):
        assert build().execution_max_consecutive_losses is None


class TestScopeConfiguration:
    def test_allowed_symbols_default_to_xauusd_only(self):
        assert build().execution_allowed_symbols_list == ["XAUUSD"]

    def test_allowed_timeframes_default_to_all_seven(self):
        assert build().execution_allowed_timeframes_list == [
            "M1", "M5", "M15", "M30", "H1", "H4", "D1",
        ]

    def test_unsupported_timeframe_is_rejected(self):
        with pytest.raises(ValidationError) as info:
            build(execution_allowed_timeframes="M15,M7")
        messages = " ".join(str(e["msg"]) for e in info.value.errors())
        assert "M7" in messages

    def test_empty_symbol_list_is_rejected(self):
        with pytest.raises(ValidationError):
            build(execution_allowed_symbols=" , ")

    def test_take_profit_policy_defaults_to_none(self):
        settings = build()
        assert settings.execution_tp_policy == "none"
        assert settings.execution_filling_policy == "auto"


class TestSafeSummary:
    def test_summary_never_contains_the_account_login_or_password(self):
        settings = build(
            execution_enabled=True,
            execution_demo_login=987654321,
            execution_demo_server="Some-Broker-Demo",
        )
        summary = settings.safe_summary()

        assert summary["execution_enabled"] is True
        assert summary["execution_demo_login_configured"] is True
        assert summary["execution_demo_server_configured"] is True
        # The raw login must never appear in a loggable summary.
        assert "987654321" not in str(summary)
        assert "execution_demo_login" not in summary
        assert "mt5_password" not in summary
