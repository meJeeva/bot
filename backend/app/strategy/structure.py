"""Confirmed M1 swing-high / swing-low detection for structure trailing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class SwingPoint:
    kind: str  # "high" or "low"
    time: int
    price: float


def detect_swings(
    highs: Sequence[float],
    lows: Sequence[float],
    times: Sequence[int],
    left: int,
    right: int,
) -> list[SwingPoint]:
    """Return confirmed swing highs/lows using a symmetric pivot window.

    A candidate at index ``i`` is confirmed only when ``left`` bars on both?
    Actually ``left`` bars to the left and ``right`` bars to the right are
    available and all are completed. Strict comparisons are used, so equal
    highs/lows do not create a swing (deterministic, no duplicate pivots).
    """
    if left < 1 or right < 1:
        return []
    n = len(highs)
    if len(lows) != n or len(times) != n or n < left + right + 1:
        return []
    result: list[SwingPoint] = []
    for i in range(left, n - right):
        high = float(highs[i])
        low = float(lows[i])
        left_highs = [float(highs[j]) for j in range(i - left, i)]
        right_highs = [float(highs[j]) for j in range(i + 1, i + right + 1)]
        left_lows = [float(lows[j]) for j in range(i - left, i)]
        right_lows = [float(lows[j]) for j in range(i + 1, i + right + 1)]
        if high > max(left_highs + right_highs):
            result.append(SwingPoint(kind="high", time=int(times[i]), price=high))
        if low < min(left_lows + right_lows):
            result.append(SwingPoint(kind="low", time=int(times[i]), price=low))
    return result


def latest_swing(swings: Sequence[SwingPoint], kind: str) -> SwingPoint | None:
    matches = [s for s in swings if s.kind == kind]
    if not matches:
        return None
    return max(matches, key=lambda s: s.time)


__all__ = ["SwingPoint", "detect_swings", "latest_swing"]