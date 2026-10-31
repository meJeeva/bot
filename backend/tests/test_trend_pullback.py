import pytest
from app.config import Settings
from app.strategy.trend_pullback import *


def make_settings(**overrides):
    overrides.setdefault("database_enabled", False)
    return Settings(_env_file=None, trend_pullback_enabled=True, **overrides)


def test_config_defaults_disabled():
    s = Settings(_env_file=None, database_enabled=False)
    assert s.trend_pullback_enabled is False
    assert s.trend_pullback_symbols_list == ["XAUUSD"]


def test_m5_bullish_and_bearish():
    # bullish
    m5 = []
    for i in range(60):
        p = 100 + i * 0.5
        m5.append({"open": p, "high": p + 1, "low": p - 0.5, "close": p + 0.5, "is_closed": True})
    assert is_m5_bullish(m5, fast_ema=5, slow_ema=10, atr_period=5) is True
    # bearish (descending)
    m5b = []
    for i in range(60):
        p = 200 - i * 0.5
        m5b.append({"open": p, "high": p + 0.5, "low": p - 1, "close": p - 0.5, "is_closed": True})
    assert is_m5_bearish(m5b, fast_ema=5, slow_ema=10, atr_period=5) is True


def test_sideways_rejected():
    m5 = []
    for i in range(60):
        m5.append({"open": 100, "high": 101, "low": 99, "close": 100, "is_closed": True})
    assert m5_trend(m5, fast_ema=5, slow_ema=10, atr_period=5) is None


def test_trigger_and_sl():
    c = {"open": 1, "high": 10, "low": 5, "close": 8, "is_closed": True}
    assert buy_trigger_price(c, entry_buffer_points=2, point=1) == 12
    assert sell_trigger_price(c, entry_buffer_points=2, point=1) == 3
    pb = PullbackInfo(index=0, candle=to_candle({"open":1,"high":2,"low":5,"close":2}), swing_low=5, swing_high=8, atr=1)
    assert buy_stop_loss(pb, sl_buffer_points=1, point=1, tick_size=1) == 4
    assert sell_stop_loss(pb, sl_buffer_points=1, point=1, tick_size=1) == 9


def test_filters():
    assert spread_ok(10, 10, point=1, max_spread_points=100, max_spread_atr_ratio=10) is True
    assert tick_fresh({"is_stale": True}) is False
    assert filters_ok(atr=0, position_open=False, already_executed=False) is False
    assert filters_ok(atr=1, position_open=True, already_executed=False) is False
    assert filters_ok(atr=1, position_open=False, already_executed=True) is False


def test_state_duplicate():
    s = make_settings()
    strat = TrendPullbackStrategy(s)
    strat.state = TrendPullbackState.WAITING_FOR_TREND
    assert strat.state == TrendPullbackState.WAITING_FOR_TREND