"""Tests for structure swing detection."""

from __future__ import annotations

from app.strategy.structure import detect_swings, latest_swing


def test_swing_low_confirmed():
    highs = [5, 4, 3, 4, 5, 6, 7]
    lows = [4, 3, 1, 3, 4, 5, 6]
    times = list(range(len(highs)))
    swings = detect_swings(highs, lows, times, 2, 2)
    lows_found = [s for s in swings if s.kind == "low"]
    assert len(lows_found) == 1
    assert lows_found[0].price == 1


def test_swing_high_confirmed():
    highs = [1, 2, 5, 2, 1, 0, 0]
    lows = [0, 1, 4, 1, 0, -1, -1]
    times = list(range(len(highs)))
    swings = detect_swings(highs, lows, times, 2, 2)
    highs_found = [s for s in swings if s.kind == "high"]
    assert len(highs_found) == 1
    assert highs_found[0].price == 5


def test_equal_highs_not_swing():
    highs = [1, 3, 3, 3, 1, 0, 0]
    lows = [0, 2, 2, 2, 0, -1, -1]
    times = list(range(len(highs)))
    swings = detect_swings(highs, lows, times, 2, 2)
    highs_found = [s for s in swings if s.kind == "high"]
    assert highs_found == []


def test_insufficient_data():
    assert detect_swings([1, 2], [0, 1], [0, 1], 2, 2) == []


def test_latest_swing():
    highs = [1, 2, 5, 2, 1, 0, 0, 1, 2, 6, 2, 1, 0]
    lows = [0, 1, 4, 1, 0, -1, -1, 0, 1, 5, 1, 0, -1]
    times = list(range(len(highs)))
    swings = detect_swings(highs, lows, times, 2, 2)
    hs = latest_swing(swings, "high")
    assert hs is not None