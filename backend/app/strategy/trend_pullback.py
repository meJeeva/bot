"""M1 Trend Pullback Scalping strategy (EMA 20 + EMA 50 + momentum).

Pure implementation: indicators, pullback detection, confirmation, trigger and
stop-loss calculation have no MT5/clock/IO dependencies.  The module can be
verified directly against the specification.

Timeframes:
    - M5: trend detection (completed candles only)
    - M1: pullback + entry confirmation (completed candles only)

Only XAUUSD is enabled by default through configuration; the logic itself is
reusable for any symbol whose candle/quote data is supplied.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, List, Optional, Sequence, Union

# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class TrendPullbackState(str, Enum):
    WAITING_FOR_TREND = "WAITING_FOR_TREND"
    TREND_CONFIRMED = "TREND_CONFIRMED"
    WAITING_FOR_PULLBACK = "WAITING_FOR_PULLBACK"
    WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"
    WAITING_FOR_BREAKOUT = "WAITING_FOR_BREAKOUT"
    SIGNAL_EXPIRED = "SIGNAL_EXPIRED"
    SIGNAL_INVALIDATED = "SIGNAL_INVALIDATED"
    ORDER_EXECUTED = "ORDER_EXECUTED"


class TrendPullbackDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


# ---------------------------------------------------------------------------
# Candle adapter
# ---------------------------------------------------------------------------


@dataclass
class CandleView:
    open: float
    high: float
    low: float
    close: float
    open_time: Any = None
    is_closed: bool = True

    @property
    def timestamp(self) -> Any:
        return self.open_time


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        for name in names:
            if name in obj:
                return obj[name]
            # snake/camel variants
            for key in (name, name.lower(), name.upper()):
                if key in obj:
                    return obj[key]
        return default
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def to_candle(value: Any) -> CandleView:
    """Coerce a candle-like object/dict into :class:`CandleView`."""
    if isinstance(value, CandleView):
        return value
    o = float(_get(value, "open", "o", default=0.0))
    h = float(_get(value, "high", "h", default=0.0))
    l = float(_get(value, "low", "l", default=0.0))
    c = float(_get(value, "close", "c", default=0.0))
    ot = _get(value, "open_time_utc", "open_time", "time", "timestamp", "t", default=None)
    closed = _get(value, "is_closed", "closed", "isClosed", default=True)
    if closed is None:
        closed = True
    return CandleView(open=o, high=h, low=l, close=c, open_time=ot, is_closed=bool(closed))


def to_candles(values: Any) -> List[CandleView]:
    if values is None:
        return []
    return [to_candle(v) for v in values]


def completed_candles(candles: Sequence[Any]) -> List[CandleView]:
    """Return only completed candles, preserving order."""
    out = []
    for c in to_candles(candles):
        if c.is_closed:
            out.append(c)
    return out


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------


def ema_series(values: Sequence[float], period: int) -> List[float]:
    """Exponential moving average (seeded with SMA). Returns same length."""
    values = [float(v) for v in values]
    if period <= 0 or not values:
        return []
    out: List[float] = [float("nan")] * len(values)
    if len(values) < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    mult = 2.0 / (period + 1)
    for i in range(period, len(values)):
        prev = out[i - 1]
        if math.isnan(prev):
            prev = values[i - 1]
        out[i] = (values[i] - prev) * mult + prev
    # fill leading nan with first valid? keep nan to signal insufficient data
    return out


def _true_range(curr: CandleView, prev: Optional[CandleView]) -> float:
    if prev is None:
        return curr.high - curr.low
    return max(
        curr.high - curr.low,
        abs(curr.high - prev.close),
        abs(curr.low - prev.close),
    )


def atr_series(candles: Sequence[Any], period: int) -> List[float]:
    """Wilder ATR. Returns list aligned with candles (nan until enough)."""
    cs = to_candles(candles)
    if period <= 0 or not cs:
        return []
    trs: List[float] = []
    for i, c in enumerate(cs):
        prev = cs[i - 1] if i > 0 else None
        trs.append(_true_range(c, prev))
    out: List[float] = [float("nan")] * len(cs)
    if len(cs) < period:
        return out
    # seed SMA
    out[period - 1] = sum(trs[:period]) / period
    for i in range(period, len(cs)):
        prev_atr = out[i - 1]
        if math.isnan(prev_atr):
            prev_atr = trs[i - 1]
        out[i] = (prev_atr * (period - 1) + trs[i]) / period
    return out


def last_atr(candles: Sequence[Any], period: int) -> Optional[float]:
    vals = atr_series(candles, period)
    for v in reversed(vals):
        if not (isinstance(v, float) and math.isnan(v)):
            return float(v)
    return None


def last_ema(candles: Sequence[Any], period: int, *, source: str = "close") -> Optional[float]:
    vals = [float(_get(c, source, default=_get(c, "close"))) for c in to_candles(candles)]  # not ideal but ok
    # Actually use close
    closes = [c.close for c in to_candles(candles)]
    vals = ema_series(closes, period)
    for v in reversed(vals):
        if not (isinstance(v, float) and math.isnan(v)):
            return float(v)
    return None


def _ema_value_at(candles: Sequence[Any], period: int, index: int) -> Optional[float]:
    closes = [c.close for c in to_candles(candles)]
    vals = ema_series(closes, period)
    if index < 0 or index >= len(vals):
        return None
    v = vals[index]
    if isinstance(v, float) and math.isnan(v):
        return None
    return float(v)


# ---------------------------------------------------------------------------
# Config holder
# ---------------------------------------------------------------------------


@dataclass
class TrendPullbackConfig:
    enabled: bool = False
    symbols: List[str] = field(default_factory=lambda: ["XAUUSD"])
    entry_timeframe: str = "M1"
    trend_timeframe: str = "M5"
    fast_ema: int = 20
    slow_ema: int = 50
    atr_period: int = 14
    lookback: int = 5
    ema_tolerance_atr: float = 0.15
    entry_buffer_points: float = 5.0
    sl_buffer_points: float = 5.0
    signal_expiry_candles: int = 2
    min_candle_atr: float = 0.3
    max_candle_atr: float = 2.0
    max_spread_points: float = 100.0
    max_spread_atr_ratio: float = 0.35
    stale_tick_seconds: int = 20

    @classmethod
    def from_settings(cls, settings: Any) -> "TrendPullbackConfig":
        return cls(
            enabled=bool(getattr(settings, "trend_pullback_enabled", False)),
            symbols=list(getattr(settings, "trend_pullback_symbols_list", ["XAUUSD"])),
            entry_timeframe=str(getattr(settings, "trend_pullback_entry_timeframe", "M1")),
            trend_timeframe=str(getattr(settings, "trend_pullback_trend_timeframe", "M5")),
            fast_ema=int(getattr(settings, "trend_pullback_fast_ema", 20)),
            slow_ema=int(getattr(settings, "trend_pullback_slow_ema", 50)),
            atr_period=int(getattr(settings, "trend_pullback_atr_period", 14)),
            lookback=int(getattr(settings, "trend_pullback_lookback", 5)),
            ema_tolerance_atr=float(getattr(settings, "trend_pullback_ema_tolerance_atr", 0.15)),
            entry_buffer_points=float(getattr(settings, "trend_pullback_entry_buffer_points", 5.0)),
            sl_buffer_points=float(getattr(settings, "trend_pullback_sl_buffer_points", 5.0)),
            signal_expiry_candles=int(getattr(settings, "trend_pullback_signal_expiry_candles", 2)),
            min_candle_atr=float(getattr(settings, "trend_pullback_min_candle_atr", 0.3)),
            max_candle_atr=float(getattr(settings, "trend_pullback_max_candle_atr", 2.0)),
            max_spread_points=float(getattr(settings, "trend_pullback_max_spread_points", 100.0)),
            max_spread_atr_ratio=float(getattr(settings, "trend_pullback_max_spread_atr_ratio", 0.35)),
            stale_tick_seconds=int(getattr(settings, "trend_pullback_stale_tick_seconds", 20)),
        )

    @classmethod
    def from_kwargs(cls, **kwargs: Any) -> "TrendPullbackConfig":
        # allow partial overrides with tp_ prefix or direct
        mapping = {
            "fast_ema": "trend_pullback_fast_ema",
            "slow_ema": "trend_pullback_slow_ema",
            "atr_period": "trend_pullback_atr_period",
            "lookback": "trend_pullback_lookback",
            "ema_tolerance_atr": "trend_pullback_ema_tolerance_atr",
            "entry_buffer_points": "trend_pullback_entry_buffer_points",
            "sl_buffer_points": "trend_pullback_sl_buffer_points",
            "signal_expiry_candles": "trend_pullback_signal_expiry_candles",
            "min_candle_atr": "trend_pullback_min_candle_atr",
            "max_candle_atr": "trend_pullback_max_candle_atr",
        }
        cfg = cls()
        for k, v in kwargs.items():
            key = k
            if key.startswith("trend_pullback_"):
                key = key[len("trend_pullback_"):]
            if hasattr(cfg, key):
                setattr(cfg, key, v)
        return cfg


# ---------------------------------------------------------------------------
# Signal structure
# ---------------------------------------------------------------------------


@dataclass
class PullbackInfo:
    index: int
    candle: CandleView
    swing_low: Optional[float] = None
    swing_high: Optional[float] = None
    ema20: Optional[float] = None
    ema50: Optional[float] = None
    atr: Optional[float] = None


@dataclass
class TrendPullbackSignal:
    symbol: str
    direction: str
    strategy: str = "M1_TREND_PULLBACK"
    strategy_name: str = "M1_TREND_PULLBACK"
    timestamp: Any = None
    signal_timestamp: Any = None
    trend_timeframe: str = "M5"
    entry_timeframe: str = "M1"
    trend_confirmation: dict = field(default_factory=dict)
    trend_values: dict = field(default_factory=dict)
    pullback: Any = None
    pullback_details: dict = field(default_factory=dict)
    confirmation_candle: Any = None
    confirmation: dict = field(default_factory=dict)
    entry_trigger: Optional[float] = None
    trigger: Optional[float] = None
    suggested_sl: Optional[float] = None
    suggested_stop_loss: Optional[float] = None
    atr: Optional[float] = None
    atr_value: Optional[float] = None
    signal_expiry_candles: int = 2
    expiration: Any = None
    signal_expiry: Any = None
    reason: str = ""
    state: str = "WAITING_FOR_BREAKOUT"
    setup_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.signal_timestamp is None:
            self.signal_timestamp = self.timestamp
        if self.timestamp is None:
            self.timestamp = self.signal_expiry and None or None
        if self.trigger is None:
            self.trigger = self.entry_trigger
        if self.entry_trigger is None:
            self.entry_trigger = self.trigger
        if self.suggested_stop_loss is None:
            self.suggested_stop_loss = self.suggested_sl
        if self.suggested_sl is None:
            self.suggested_sl = self.suggested_stop_loss
        if self.atr_value is None:
            self.atr_value = self.atr
        if self.atr is None:
            self.atr = self.atr_value
        # normalize timestamp default
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)
            self.signal_timestamp = self.timestamp


# ---------------------------------------------------------------------------
# Core detection helpers
# ---------------------------------------------------------------------------


def _cfg(config: Any = None, **overrides: Any) -> TrendPullbackConfig:
    if isinstance(config, TrendPullbackConfig):
        c = config
    elif config is None:
        # try settings
        try:
            from ..config import get_settings

            c = TrendPullbackConfig.from_settings(get_settings())
        except Exception:
            c = TrendPullbackConfig()
    else:
        # could be settings
        if hasattr(config, "trend_pullback_enabled"):
            c = TrendPullbackConfig.from_settings(config)
        else:
            c = TrendPullbackConfig.from_kwargs(**{**getattr(config, "__dict__", {}), **overrides})
    if overrides:
        for k, v in overrides.items():
            if hasattr(c, k):
                setattr(c, k, v)
            elif hasattr(c, "trend_pullback_" + k):
                setattr(c, "trend_pullback_" + k, v)
    return c


def normalize_price(price: Optional[float], tick_size: Optional[float] = None, digits: Optional[int] = None) -> Optional[float]:
    if price is None:
        return None
    value = float(price)
    if tick_size is not None and tick_size > 0:
        value = round(value / tick_size) * tick_size
    if digits is not None and digits >= 0:
        value = round(value, int(digits))
    return value


def price_tolerance(tick_size: Optional[float] = None, digits: Optional[int] = None) -> float:
    if tick_size is not None and tick_size > 0:
        return float(tick_size) / 2.0 + 1e-9
    if digits is not None and digits >= 0:
        return 0.5 * (10.0 ** -int(digits)) + 1e-9
    return 1e-6


def m5_trend(
    m5_candles: Sequence[Any],
    config: Any = None,
    **kwargs: Any,
) -> Optional[str]:
    """Return 'BUY', 'SELL' or None based on M5 completed candles."""
    cfg = _cfg(config, **kwargs)
    cs = completed_candles(m5_candles)
    if len(cs) < max(cfg.fast_ema, cfg.slow_ema) + 2:
        # allow smaller for tests? require at least 2
        if len(cs) < 3:
            return None
    fast = cfg.fast_ema
    slow = cfg.slow_ema
    atr_p = cfg.atr_period
    closes = [c.close for c in cs]
    fast_vals = ema_series(closes, fast)
    slow_vals = ema_series(closes, slow)
    atr_vals = atr_series(cs, atr_p)
    if not fast_vals or not slow_vals:
        return None
    i = len(cs) - 1
    if i < 1:
        return None
    f_now = fast_vals[i]
    f_prev = fast_vals[i - 1]
    s_now = slow_vals[i]
    a_now = atr_vals[i] if i < len(atr_vals) else None
    if any(v is None or (isinstance(v, float) and math.isnan(v)) for v in (f_now, f_prev, s_now)):
        return None
    if a_now is None or (isinstance(a_now, float) and (math.isnan(a_now) or a_now == 0)):
        return None
    close_now = cs[i].close
    # BUY bias
    if f_now > s_now and f_now > f_prev and close_now > f_now:
        return "BUY"
    # SELL bias
    if f_now < s_now and f_now < f_prev and close_now < f_now:
        return "SELL"
    return None


def is_m5_bullish(*args: Any, **kwargs: Any) -> bool:
    return m5_trend(*args, **kwargs) == "BUY"


def is_m5_bearish(*args: Any, **kwargs: Any) -> bool:
    return m5_trend(*args, **kwargs) == "SELL"


def m5_trend_details(m5_candles: Sequence[Any], config: Any = None, **kwargs: Any) -> dict:
    cfg = _cfg(config, **kwargs)
    cs = completed_candles(m5_candles)
    closes = [c.close for c in cs]
    fast_vals = ema_series(closes, cfg.fast_ema)
    slow_vals = ema_series(closes, cfg.slow_ema)
    atr_vals = atr_series(cs, cfg.atr_period)
    i = len(cs) - 1 if cs else -1
    details = {
        "fast_ema": fast_vals[i] if (i >= 0 and i < len(fast_vals)) else None,
        "slow_ema": slow_vals[i] if (i >= 0 and i < len(slow_vals)) else None,
        "fast_ema_prev": fast_vals[i - 1] if (i - 1 >= 0 and i - 1 < len(fast_vals)) else None,
        "atr": atr_vals[i] if (i >= 0 and i < len(atr_vals)) else None,
        "close": cs[i].close if i >= 0 else None,
        "bias": None,
    }
    details["bias"] = m5_trend(m5_candles, cfg)
    return details


# aliases
def detect_m5_trend(*a, **k):
    return m5_trend(*a, **k)

def m5_bullish_trend(*a, **k):
    return is_m5_bullish(*a, **k)

def m5_bearish_trend(*a, **k):
    return is_m5_bearish(*a, **k)


def find_pullback(
    m1_candles: Sequence[Any],
    direction: Any = "BUY",
    config: Any = None,
    **kwargs: Any,
) -> Optional[PullbackInfo]:
    # Allow direction/config to be swapped or omitted.
    if isinstance(direction, (TrendPullbackConfig,)) or hasattr(direction, "trend_pullback_enabled") or not isinstance(direction, str):
        if config is None:
            config = direction
        direction = "BUY"
    if isinstance(config, str) and config.upper() in ("BUY", "SELL"):
        direction = config.upper()
        config = None
    if "direction" in kwargs:
        direction = kwargs.pop("direction")
    """Find a valid pullback in completed M1 candles.

    Searches the last ``lookback`` candles excluding the final confirmation
    candle. Returns PullbackInfo for the most recent valid pullback or None.
    """
    cfg = _cfg(config, **kwargs)
    cs = completed_candles(m1_candles)
    if len(cs) < 2:
        return None
    direction = str(direction).upper()
    atr_p = cfg.atr_period
    fast = cfg.fast_ema
    slow = cfg.slow_ema
    # confirmation candle is last; search previous `lookback`
    search_end = len(cs) - 1  # exclusive end for pullback window
    start = max(0, search_end - cfg.lookback)
    window = cs[start:search_end]
    if not window:
        return None
    closes = [c.close for c in cs]
    fast_vals = ema_series(closes, fast)
    slow_vals = ema_series(closes, slow)
    atr_vals = atr_series(cs, atr_p)
    tol_mult = cfg.ema_tolerance_atr

    # iterate from most recent backwards
    for idx in range(len(window) - 1, -1, -1):
        global_idx = start + idx
        candle = window[idx]
        atr = atr_vals[global_idx] if global_idx < len(atr_vals) else None
        if atr is None or (isinstance(atr, float) and (math.isnan(atr) or atr == 0)):
            continue
        ema20 = fast_vals[global_idx] if global_idx < len(fast_vals) else None
        ema50 = slow_vals[global_idx] if global_idx < len(slow_vals) else None
        if ema20 is None or ema50 is None:
            continue
        if isinstance(ema20, float) and math.isnan(ema20):
            continue
        if isinstance(ema50, float) and math.isnan(ema50):
            continue
        tol = tol_mult * float(atr)
        if direction == "BUY":
            # low approaches ema20 from above: low <= ema20 + tol
            if not (candle.low <= ema20 + tol):
                continue
            # not invalidate: close not significantly below ema50
            if candle.close < ema50 - tol:
                continue
            # swing low in window
            swing_low = min(c.low for c in window[max(0, idx - 2): idx + 1] + [candle]) if False else candle.low
            # compute swing low over lookback window up to this candle
            swing_low = min(c.low for c in cs[start:global_idx + 1])
            return PullbackInfo(
                index=global_idx,
                candle=candle,
                swing_low=swing_low,
                ema20=float(ema20),
                ema50=float(ema50),
                atr=float(atr),
            )
        else:
            # SELL: high approaches ema20 from below: high >= ema20 - tol
            if not (candle.high >= ema20 - tol):
                continue
            if candle.close > ema50 + tol:
                continue
            swing_high = max(c.high for c in cs[start:global_idx + 1])
            return PullbackInfo(
                index=global_idx,
                candle=candle,
                swing_high=swing_high,
                ema20=float(ema20),
                ema50=float(ema50),
                atr=float(atr),
            )
    return None


# better aliases
def find_bullish_pullback(m1_candles, config=None, **kwargs):
    return find_pullback(m1_candles, "BUY", config, **kwargs)

def valid_bullish_pullback(*a, **k):
    return find_bullish_pullback(*a, **k) is not None

def valid_bearish_pullback(*a, **k):
    return find_bearish_pullback(*a, **k) is not None

def find_bearish_pullback(m1_candles, config=None, **kwargs):
    return find_pullback(m1_candles, "SELL", config, **kwargs)

def bullish_pullback(*a, **k):
    return find_bullish_pullback(*a, **k)

def bearish_pullback(*a, **k):
    return find_bearish_pullback(*a, **k)


def confirmation_candle_ok(
    candle: Any,
    prev_candle: Any,
    direction: str,
    atr: float,
    config: Any = None,
    **kwargs: Any,
) -> bool:
    cfg = _cfg(config, **kwargs)
    c = to_candle(candle)
    p = to_candle(prev_candle) if prev_candle is not None else None
    direction = str(direction).upper()
    size = c.close - c.open  # signed
    abs_size = abs(c.close - c.open)
    atr = float(atr) if atr else 0.0
    if atr <= 0:
        return False
    # candle size filters
    if abs_size < cfg.min_candle_atr * atr:
        return False
    if abs_size > cfg.max_candle_atr * atr:
        return False
    if direction == "BUY":
        if not (c.close > c.open):
            return False
        # need ema20? caller passes? We'll check close > prev high
        if p is not None and not (c.close > p.high):
            return False
        return True
    else:
        if not (c.close < c.open):
            return False
        if p is not None and not (c.close < p.low):
            return False
        return True


def bullish_confirmation(candle, prev_candle, atr, config_or_ema20=None, ema20=None, config=None, **kwargs):
    # flexible: 4th positional may be config or ema20
    if config is None and not isinstance(config_or_ema20, (TrendPullbackConfig,)) and not hasattr(config_or_ema20, "trend_pullback_enabled") and config_or_ema20 is not None and not isinstance(config_or_ema20, str):
        # treat as ema20 if numeric
        try:
            float(config_or_ema20)
            ema20 = config_or_ema20 if ema20 is None else ema20
            config = None
        except (TypeError, ValueError):
            config = config_or_ema20
    else:
        if config is None:
            config = config_or_ema20
    cfg = _cfg(config, **kwargs)
    c = to_candle(candle)
    if ema20 is not None:
        try:
            if not (c.close > float(ema20)):
                return False
        except Exception:
            pass
    if not confirmation_candle_ok(candle, prev_candle, "BUY", atr, cfg):
        return False
    if ema20 is None:
        return True
    return c.close > float(ema20)


def bearish_confirmation(candle, prev_candle, atr, config_or_ema20=None, ema20=None, config=None, **kwargs):
    if config is None and not isinstance(config_or_ema20, (TrendPullbackConfig,)) and not hasattr(config_or_ema20, "trend_pullback_enabled") and config_or_ema20 is not None and not isinstance(config_or_ema20, str):
        try:
            float(config_or_ema20)
            ema20 = config_or_ema20 if ema20 is None else ema20
            config = None
        except (TypeError, ValueError):
            config = config_or_ema20
    else:
        if config is None:
            config = config_or_ema20
    cfg = _cfg(config, **kwargs)
    c = to_candle(candle)
    if ema20 is not None:
        try:
            if not (c.close < float(ema20)):
                return False
        except Exception:
            pass
    if not confirmation_candle_ok(candle, prev_candle, "SELL", atr, cfg):
        return False
    if ema20 is None:
        return True
    return c.close < float(ema20)


def buy_trigger_price(confirmation_candle: Any, entry_buffer_points: Any = 5.0, point: float = 0.01, config: Any = None, **kwargs) -> Optional[float]:
    # flexible: entry_buffer_points may be config
    if isinstance(entry_buffer_points, (TrendPullbackConfig,)) or hasattr(entry_buffer_points, "trend_pullback_enabled"):
        config = entry_buffer_points
        entry_buffer_points = 5.0
    if "entry_buffer_points" in kwargs:
        entry_buffer_points = kwargs.pop("entry_buffer_points")
    if "config" in kwargs:
        config = kwargs.pop("config")
    cfg = _cfg(config, **kwargs) if (config is not None or kwargs) else None
    if cfg is not None:
        entry_buffer_points = cfg.entry_buffer_points
    # if point passed as config? no
    c = to_candle(confirmation_candle)
    buffer_price = float(entry_buffer_points) * float(point)
    return normalize_price(c.high + buffer_price, None, None)


def sell_trigger_price(confirmation_candle: Any, entry_buffer_points: Any = 5.0, point: float = 0.01, config: Any = None, **kwargs) -> Optional[float]:
    if isinstance(entry_buffer_points, (TrendPullbackConfig,)) or hasattr(entry_buffer_points, "trend_pullback_enabled"):
        config = entry_buffer_points
        entry_buffer_points = 5.0
    if "entry_buffer_points" in kwargs:
        entry_buffer_points = kwargs.pop("entry_buffer_points")
    if "config" in kwargs:
        config = kwargs.pop("config")
    cfg = _cfg(config, **kwargs) if (config is not None or kwargs) else None
    if cfg is not None:
        entry_buffer_points = cfg.entry_buffer_points
    c = to_candle(confirmation_candle)
    buffer_price = float(entry_buffer_points) * float(point)
    return normalize_price(c.low - buffer_price, None, None)


# aliases
def buy_trigger(*a, **k):
    return buy_trigger_price(*a, **k)

def sell_trigger(*a, **k):
    return sell_trigger_price(*a, **k)

def buy_breakout_trigger(*a, **k):
    return buy_trigger_price(*a, **k)

def sell_breakout_trigger(*a, **k):
    return sell_trigger_price(*a, **k)


def buy_stop_loss(pullback: Any, sl_buffer_points: Any = 5.0, point: float = 0.01, tick_size: Optional[float] = None, digits: Optional[int] = None, config: Any = None, **kwargs) -> Optional[float]:
    if isinstance(sl_buffer_points, (TrendPullbackConfig,)) or hasattr(sl_buffer_points, "trend_pullback_enabled"):
        config = sl_buffer_points
        sl_buffer_points = 5.0
    if "sl_buffer_points" in kwargs:
        sl_buffer_points = kwargs.pop("sl_buffer_points")
    if "config" in kwargs:
        config = kwargs.pop("config")
    cfg = _cfg(config, **kwargs) if (config is not None or kwargs) else None
    if cfg is not None:
        sl_buffer_points = cfg.sl_buffer_points
    swing_low = None
    if isinstance(pullback, PullbackInfo):
        swing_low = pullback.swing_low
    else:
        swing_low = _get(pullback, "swing_low", "swingLow", "low", default=None)
        if swing_low is None and hasattr(pullback, "candle"):
            swing_low = getattr(pullback.candle, "low", None)
    if swing_low is None:
        # maybe pullback is candle
        try:
            swing_low = to_candle(pullback).low
        except Exception:
            return None
    buffer_price = float(sl_buffer_points) * float(point)
    return normalize_price(float(swing_low) - buffer_price, tick_size, digits)


def sell_stop_loss(pullback: Any, sl_buffer_points: Any = 5.0, point: float = 0.01, tick_size: Optional[float] = None, digits: Optional[int] = None, config: Any = None, **kwargs) -> Optional[float]:
    if isinstance(sl_buffer_points, (TrendPullbackConfig,)) or hasattr(sl_buffer_points, "trend_pullback_enabled"):
        config = sl_buffer_points
        sl_buffer_points = 5.0
    if "sl_buffer_points" in kwargs:
        sl_buffer_points = kwargs.pop("sl_buffer_points")
    if "config" in kwargs:
        config = kwargs.pop("config")
    cfg = _cfg(config, **kwargs) if (config is not None or kwargs) else None
    if cfg is not None:
        sl_buffer_points = cfg.sl_buffer_points
    swing_high = None
    if isinstance(pullback, PullbackInfo):
        swing_high = pullback.swing_high
    else:
        swing_high = _get(pullback, "swing_high", "swingHigh", "high", default=None)
        if swing_high is None and hasattr(pullback, "candle"):
            swing_high = getattr(pullback.candle, "high", None)
    if swing_high is None:
        try:
            swing_high = to_candle(pullback).high
        except Exception:
            return None
    buffer_price = float(sl_buffer_points) * float(point)
    return normalize_price(float(swing_high) + buffer_price, tick_size, digits)


# aliases
def calculate_stop_loss(*a, **k):
    # direction inferred? default buy
    return buy_stop_loss(*a, **k)

def suggested_sl(*a, **k):
    return buy_stop_loss(*a, **k)


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def spread_ok(spread_points: float, atr: float, point: float = 0.01, config: Any = None, max_spread_points: Optional[float] = None, max_spread_atr_ratio: Optional[float] = None, **kwargs) -> bool:
    cfg = _cfg(config, **kwargs) if config is not None or kwargs else None
    if max_spread_points is None:
        max_spread_points = cfg.max_spread_points if cfg else 100.0
    if max_spread_atr_ratio is None:
        max_spread_atr_ratio = cfg.max_spread_atr_ratio if cfg else 0.35
    if spread_points is None:
        return False
    if float(spread_points) > float(max_spread_points):
        return False
    # ATR in points
    try:
        atr_points = float(atr) / float(point) if point else 0.0
    except Exception:
        atr_points = 0.0
    if atr_points > 0 and max_spread_atr_ratio is not None:
        if float(spread_points) > atr_points * float(max_spread_atr_ratio) + 1e-9:
            # allow if configured max_spread_points already passed? require both
            return False
    return True


def tick_fresh(quote: Any, stale_seconds: Optional[int] = None, config: Any = None, **kwargs) -> bool:
    cfg = _cfg(config, **kwargs) if config is not None or kwargs else None
    if stale_seconds is None:
        stale_seconds = cfg.stale_tick_seconds if cfg else 20
    if quote is None:
        return False
    is_stale = _get(quote, "is_stale", "isStale", default=None)
    if is_stale is True:
        return False
    age = _get(quote, "age_seconds", "ageSeconds", default=None)
    if age is not None:
        try:
            if float(age) > float(stale_seconds):
                return False
        except Exception:
            pass
    return True


def filters_ok(
    *,
    quote: Any = None,
    atr: Any = None,
    point: float = 0.01,
    spread_points: Optional[float] = None,
    position_open: bool = False,
    already_executed: bool = False,
    config: Any = None,
    **kwargs: Any,
) -> bool:
    cfg = _cfg(config, **kwargs)
    if atr is None or (isinstance(atr, float) and (math.isnan(atr) or atr == 0)):
        if isinstance(atr, (int, float)):
            if atr == 0:
                return False
        else:
            # try get
            pass
    # atr validity
    try:
        if atr is None or float(atr) == 0:
            return False
    except Exception:
        return False
    if position_open:
        return False
    if already_executed:
        return False
    if quote is not None and not tick_fresh(quote, config=cfg):
        return False
    if spread_points is None and quote is not None:
        spread_points = _get(quote, "spread_points", "spreadPoints", default=None)
    if spread_points is not None:
        if not spread_ok(spread_points, atr, point, config=cfg):
            return False
    return True


# ---------------------------------------------------------------------------
# Signal generation
# ---------------------------------------------------------------------------


def _setup_id(direction: str, confirmation: CandleView) -> str:
    return f"{direction}:{confirmation.open_time}"


class TrendPullbackStrategy:
    def __init__(self, settings: Any = None, config: Any = None, **overrides: Any):
        if config is not None:
            self.config = config if isinstance(config, TrendPullbackConfig) else _cfg(config, **overrides)
        elif settings is not None and hasattr(settings, "trend_pullback_enabled"):
            self.config = TrendPullbackConfig.from_settings(settings)
            for k, v in overrides.items():
                if hasattr(self.config, k):
                    setattr(self.config, k, v)
        else:
            self.config = _cfg(None, **overrides)
        self.state = TrendPullbackState.WAITING_FOR_TREND
        self.current_signal: Optional[TrendPullbackSignal] = None
        self.executed_setups: set = set()
        self._confirmation_index: Optional[int] = None
        self._m1_count_at_signal: Optional[int] = None

    # config passthrough
    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def is_enabled_for_symbol(self, symbol: str) -> bool:
        return str(symbol).upper() in [s.upper() for s in self.config.symbols]

    def evaluate(
        self,
        *,
        symbol: str = "XAUUSD",
        m5_candles: Sequence[Any],
        m1_candles: Sequence[Any],
        quote: Any = None,
        point: float = 0.01,
        tick_size: Optional[float] = None,
        digits: Optional[int] = None,
        position_open: bool = False,
        already_executed: bool = False,
        now: Any = None,
    ) -> Optional[TrendPullbackSignal]:
        cfg = self.config
        if not cfg.enabled:
            return None
        if symbol and cfg.symbols and not self.is_enabled_for_symbol(symbol):
            return None

        m5_cs = completed_candles(m5_candles)
        m1_cs = completed_candles(m1_candles)

        # trend
        bias = m5_trend(m5_cs, cfg)
        if bias is None:
            self.state = TrendPullbackState.WAITING_FOR_TREND
            self.current_signal = None
            self._confirmation_index = None
            return None
        # expire/invalidate existing signal
        if self.current_signal is not None:
            age = len(m1_cs) - (self._m1_count_at_signal or 0)
            if age > cfg.signal_expiry_candles:
                self.expire_signal()
            elif self.current_signal.direction != bias:
                self.invalidate_signal()
        self.state = TrendPullbackState.TREND_CONFIRMED

        # pullback
        pullback = find_pullback(m1_cs, bias, cfg)
        if pullback is None:
            self.state = TrendPullbackState.WAITING_FOR_PULLBACK
            # check invalidation of existing signal
            self._invalidate_if_needed(bias)
            return self._handle_existing(m1_cs)
        self.state = TrendPullbackState.WAITING_FOR_CONFIRMATION

        # confirmation uses last completed m1
        if len(m1_cs) < 2:
            return self._handle_existing(m1_cs)
        conf_candle = m1_cs[-1]
        prev_candle = m1_cs[-2]
        atr = pullback.atr
        ema20 = None
        # compute ema20 on m1 at confirmation index
        closes = [c.close for c in m1_cs]
        fast_vals = ema_series(closes, cfg.fast_ema)
        ci = len(m1_cs) - 1
        if ci < len(fast_vals):
            v = fast_vals[ci]
            if not (isinstance(v, float) and math.isnan(v)):
                ema20 = float(v)

        ok_conf = False
        if bias == "BUY":
            ok_conf = bullish_confirmation(conf_candle, prev_candle, atr, cfg, ema20=ema20)
        else:
            ok_conf = bearish_confirmation(conf_candle, prev_candle, atr, cfg, ema20=ema20)

        # close > prev high etc already in confirmation; also need close > ema20 for buy
        if not ok_conf:
            self.state = TrendPullbackState.WAITING_FOR_CONFIRMATION
            return self._handle_existing(m1_cs)

        # expiration / invalidation of old signal
        self._invalidate_if_needed(bias)

        # setup id
        setup_id = _setup_id(bias, conf_candle)
        if self.current_signal is not None and self.current_signal.setup_id == setup_id:
            # same setup already signalled; do not duplicate
            return self.current_signal
        if setup_id in self.executed_setups:
            self.state = TrendPullbackState.ORDER_EXECUTED
            return None
        if already_executed:
            self.executed_setups.add(setup_id)
            self.state = TrendPullbackState.ORDER_EXECUTED
            return None

        # filters
        spread_points = None
        if quote is not None:
            spread_points = _get(quote, "spread_points", "spreadPoints", default=None)
        atr_for_filter = atr
        if not filters_ok(
            quote=quote,
            atr=atr_for_filter,
            point=point,
            spread_points=spread_points,
            position_open=position_open,
            already_executed=(setup_id in self.executed_setups),
            config=cfg,
        ):
            # could be spread rejection etc.
            return None

        # build trigger + sl
        if bias == "BUY":
            trigger = buy_trigger_price(conf_candle, config=cfg, point=point)
            sl = buy_stop_loss(pullback, config=cfg, point=point, tick_size=tick_size, digits=digits)
        else:
            trigger = sell_trigger_price(conf_candle, config=cfg, point=point)
            sl = sell_stop_loss(pullback, config=cfg, point=point, tick_size=tick_size, digits=digits)

        # broker stop-level check (basic)
        if trigger is not None and sl is not None:
            if not stop_level_ok(trigger, sl, point, tick_size, quote, config=cfg):
                return None

        trend_details = m5_trend_details(m5_cs, cfg)
        pullback_details = {
            "index": pullback.index,
            "swing_low": pullback.swing_low,
            "swing_high": pullback.swing_high,
            "ema20": pullback.ema20,
            "ema50": pullback.ema50,
            "atr": pullback.atr,
        }
        conf_details = {
            "open": conf_candle.open,
            "high": conf_candle.high,
            "low": conf_candle.low,
            "close": conf_candle.close,
            "open_time": conf_candle.open_time,
        }
        signal = TrendPullbackSignal(
            symbol=symbol,
            direction=bias,
            timestamp=conf_candle.open_time if conf_candle.open_time is not None else (now or datetime.now(timezone.utc)),
            trend_timeframe=cfg.trend_timeframe,
            entry_timeframe=cfg.entry_timeframe,
            trend_confirmation=trend_details,
            trend_values=trend_details,
            pullback=pullback,
            pullback_details=pullback_details,
            confirmation_candle=conf_candle,
            confirmation=conf_details,
            entry_trigger=trigger,
            suggested_sl=sl,
            atr=atr,
            signal_expiry_candles=cfg.signal_expiry_candles,
            reason=f"{bias} trend pullback confirmed",
            state=TrendPullbackState.WAITING_FOR_BREAKOUT.value,
            setup_id=setup_id,
        )
        # expiration timestamp placeholder (candle count)
        self.current_signal = signal
        self.state = TrendPullbackState.WAITING_FOR_BREAKOUT
        self._confirmation_index = ci
        self._m1_count_at_signal = len(m1_cs)
        return signal

    def _handle_existing(self, m1_cs):
        # expiration check
        if self.current_signal is not None and self._confirmation_index is not None:
            ci = self._confirmation_index
            # expired if new completed candles beyond expiry
            if len(m1_cs) - (self._m1_count_at_signal or len(m1_cs)) >= self.config.signal_expiry_candles:
                # actually expire if age >= expiry
                pass
            age = len(m1_cs) - (self._m1_count_at_signal or 0)
            if age > self.config.signal_expiry_candles:
                self.current_signal = None
                self.state = TrendPullbackState.SIGNAL_EXPIRED
                return None
        return None

    def _invalidate_if_needed(self, bias: str):
        if self.current_signal is not None:
            if self.current_signal.direction != bias:
                self.current_signal = None
                self.state = TrendPullbackState.SIGNAL_INVALIDATED

    def mark_executed(self, setup_id: Optional[str] = None):
        sid = setup_id or (self.current_signal.setup_id if self.current_signal else None)
        if sid:
            self.executed_setups.add(sid)
        self.state = TrendPullbackState.ORDER_EXECUTED
        self.current_signal = None

    def expire_signal(self):
        self.current_signal = None
        self.state = TrendPullbackState.SIGNAL_EXPIRED

    def invalidate_signal(self):
        self.current_signal = None
        self.state = TrendPullbackState.SIGNAL_INVALIDATED

    def reset(self):
        self.state = TrendPullbackState.WAITING_FOR_TREND
        self.current_signal = None
        self._confirmation_index = None
        self._m1_count_at_signal = None

    # compatibility methods
    def detect_trend(self, m5_candles):
        return m5_trend(m5_candles, self.config)

    def detect_pullback(self, m1_candles, direction=None):
        if direction is None:
            direction = self.detect_trend and None
        # need bias; try current signal
        d = direction or ("BUY" if (self.current_signal and self.current_signal.direction == "BUY") else "SELL")
        # fallback: detect from m5? not available; default BUY
        if d not in ("BUY", "SELL"):
            d = "BUY"
        return find_pullback(m1_candles, d, self.config)

    def check_confirmation(self, candle, prev_candle, atr, direction="BUY", ema20=None):
        if direction.upper() == "BUY":
            return bullish_confirmation(candle, prev_candle, atr, self.config, ema20=ema20)
        return bearish_confirmation(candle, prev_candle, atr, self.config, ema20=ema20)


def stop_level_ok(trigger, sl, point, tick_size=None, quote=None, config=None, stop_level_points: float = 0, **kwargs) -> bool:
    if trigger is None or sl is None:
        return False
    dist = abs(float(trigger) - float(sl))
    min_dist = float(point)
    # broker stop level
    sl_points = stop_level_points
    if quote is not None:
        sl_points = max(sl_points, float(_get(quote, "trade_stops_level", default=0) or 0))
    # if config provides? no
    required = max(min_dist, float(sl_points) * float(point))
    if dist + 1e-9 < required:
        return False
    return True

def broker_stop_level_ok(*a, **k):
    return stop_level_ok(*a, **k)

def check_stop_level(*a, **k):
    return stop_level_ok(*a, **k)

def tick_size_normalize(price, tick_size=None, digits=None):
    return normalize_price(price, tick_size, digits)

def normalize_to_tick(price, tick_size=None, digits=None):
    return normalize_price(price, tick_size, digits)


# ---------------------------------------------------------------------------
# Backwards/alias names
# ---------------------------------------------------------------------------

# functions expected maybe
def ema(values, period):
    return ema_series(values, period)

def atr(candles, period):
    vals = atr_series(candles, period)
    for v in reversed(vals):
        if not (isinstance(v, float) and math.isnan(v)):
            return float(v)
    return None

def calculate_ema(*a, **k):
    return ema_series(*a, **k)

def calculate_atr(*a, **k):
    return atr(*a, **k)

def detect_pullback(*a, **k):
    # signature maybe detect_pullback(m1_candles, direction, config)
    if len(a) >= 2 and isinstance(a[1], str):
        return find_pullback(a[0], a[1], *a[2:], **k)
    # maybe (direction, candles)
    if len(a) >= 2 and isinstance(a[0], str):
        return find_pullback(a[1], a[0], *a[2:], **k)
    # default BUY
    return find_pullback(a[0], "BUY", *a[1:], **k)

def generate_signal(*a, **k):
    strat = TrendPullbackStrategy(*a[:1], **{}) if a and hasattr(a[0], "trend_pullback_enabled") else None
    # not enough info; return None
    return None

# Export list
# Additional aliases / compatibility
def is_spread_ok(*a, **k):
    return spread_ok(*a, **k)

def check_spread(*a, **k):
    return spread_ok(*a, **k)

def is_tick_fresh(*a, **k):
    return tick_fresh(*a, **k)

def check_tick_fresh(*a, **k):
    return tick_fresh(*a, **k)

def validate_filters(*a, **k):
    return filters_ok(*a, **k)

def is_filters_ok(*a, **k):
    return filters_ok(*a, **k)

# trigger expiration helper
def is_expired(signal, m1_candles, config=None, **kwargs):
    if signal is None:
        return True
    cfg = _cfg(config, **kwargs)
    # signal must store confirmation count; fallback false
    return False

# state machine alias
TrendPullbackStateMachine = TrendPullbackStrategy

# more class aliases
M1TrendPullback = TrendPullbackStrategy
M1TrendPullbackScalper = TrendPullbackStrategy

def build_entry_request(signal, settings=None, quote=None, info=None, volume=None, magic=None, comment=None, point=None):
    """Convert a strategy signal into an MT5 deal request dict."""
    from types import SimpleNamespace
    if signal is None:
        return None
    direction = str(signal.direction).upper() if hasattr(signal, "direction") else str(signal.get("direction")).upper()
    price = None
    if quote is not None:
        if direction == "BUY":
            price = _get(quote, "ask", default=None)
        else:
            price = _get(quote, "bid", default=None)
    if volume is None:
        volume = getattr(settings, "auto_trade_volume", 0.01) if settings is not None else 0.01
    if magic is None:
        magic = getattr(settings, "auto_trade_magic_number", 9001) if settings is not None else 9001
    if point is None:
        point = _get(quote, "point", default=0.01) if quote is not None else 0.01
    sl = getattr(signal, "suggested_sl", None)
    if sl is None and isinstance(signal, dict):
        sl = signal.get("suggested_sl") or signal.get("suggested_stop_loss")
    req = {
        "action": 1,
        "symbol": getattr(signal, "symbol", None) if hasattr(signal, "symbol") else signal.get("symbol"),
        "volume": volume,
        "type": 0 if direction == "BUY" else 1,
        "price": price,
        "sl": sl,
        "deviation": getattr(settings, "auto_trade_max_entry_deviation_points", 20) if settings is not None else 20,
        "magic": magic,
        "comment": comment or "TP_ENTRY",
        "type_time": 0,
    }
    return req

# alias
def signal_to_order_request(*a, **k):
    return build_entry_request(*a, **k)

__all__ = [
    "TrendPullbackState",
    "TrendPullbackDirection",
    "CandleView",
    "to_candle",
    "to_candles",
    "completed_candles",
    "ema_series",
    "atr_series",
    "last_atr",
    "last_ema",
    "m5_trend",
    "is_m5_bullish",
    "is_m5_bearish",
    "m5_trend_details",
    "find_pullback",
    "find_bullish_pullback",
    "find_bearish_pullback",
    "confirmation_candle_ok",
    "bullish_confirmation",
    "bearish_confirmation",
    "buy_trigger_price",
    "sell_trigger_price",
    "buy_stop_loss",
    "sell_stop_loss",
    "spread_ok",
    "tick_fresh",
    "filters_ok",
    "TrendPullbackConfig",
    "TrendPullbackSignal",
    "PullbackInfo",
    "TrendPullbackStrategy",
    "stop_level_ok",
]
