"""ATR calculation and adaptive trailing-distance helpers.

ATR is calculated in actual XAUUSD price units from completed M1 candles only.
Wilder smoothing is used with an SMA initialisation over the first ``period``
true ranges.
"""

from __future__ import annotations

import math
from typing import Sequence


def true_range(high: float, low: float, prev_close: float | None = None) -> float:
    if prev_close is None:
        return float(high) - float(low)
    return max(
        float(high) - float(low),
        abs(float(high) - float(prev_close)),
        abs(float(low) - float(prev_close)),
    )


def wilder_atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int,
) -> float | None:
    """Return Wilder-smoothed ATR or ``None`` if data is insufficient/invalid."""
    if period < 2:
        return None
    if len(highs) != len(lows) or len(highs) != len(closes):
        return None
    if len(highs) < period:
        return None
    trs = [true_range(highs[i], lows[i], closes[i - 1] if i > 0 else None) for i in range(len(highs))]
    if any(not math.isfinite(v) or v < 0 for v in trs):
        return None
    atr = sum(trs[:period]) / float(period)
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / float(period)
    if not math.isfinite(atr) or atr <= 0:
        return None
    return float(atr)


def atr_trailing_distance(atr: float | None, multiplier: float) -> float | None:
    if atr is None or not math.isfinite(atr) or atr <= 0:
        return None
    if not math.isfinite(multiplier) or multiplier <= 0:
        return None
    value = float(atr) * float(multiplier)
    if not math.isfinite(value) or value <= 0:
        return None
    return value


def buy_candidate_stop(high_water: float, distance: float) -> float:
    return float(high_water) - float(distance)


def sell_candidate_stop(low_water: float, distance: float) -> float:
    return float(low_water) + float(distance)


__all__ = [
    "atr_trailing_distance",
    "buy_candidate_stop",
    "sell_candidate_stop",
    "true_range",
    "wilder_atr",
]