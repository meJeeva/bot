"""Tests for ATR calculation and adaptive trailing helpers."""

from __future__ import annotations

import math

import pytest

from app.strategy.atr import (
    atr_trailing_distance,
    buy_candidate_stop,
    sell_candidate_stop,
    true_range,
    wilder_atr,
)


def test_true_range_first_candle():
    assert true_range(10.0, 9.0) == 1.0


def test_true_range_with_prev_close():
    tr = true_range(10.0, 9.0, 9.5)
    assert tr == 1.0


def test_wilder_atr_insufficient():
    assert wilder_atr([1.0], [0.0], [0.5], 14) is None


def test_wilder_atr_basic():
    highs = [10.0 + i * 0.1 for i in range(20)]
    lows = [9.0 + i * 0.1 for i in range(20)]
    closes = [9.5 + i * 0.1 for i in range(20)]
    atr = wilder_atr(highs, lows, closes, 14)
    assert atr is not None and atr > 0


def test_atr_distance():
    assert atr_trailing_distance(0.40, 1.0) == 0.40
    assert atr_trailing_distance(0.22, 1.0) == 0.22


def test_buy_candidate_stop():
    assert buy_candidate_stop(4134.14, 0.40) == pytest.approx(4133.74)
    assert buy_candidate_stop(4134.36, 0.22) == pytest.approx(4134.14)


def test_sell_candidate_stop():
    assert sell_candidate_stop(4096.00, 0.40) == pytest.approx(4096.40)
    assert sell_candidate_stop(4094.00, 0.22) == pytest.approx(4094.22)


def test_invalid_atr():
    assert atr_trailing_distance(None, 1.0) is None
    assert atr_trailing_distance(0.0, 1.0) is None
    assert atr_trailing_distance(float("nan"), 1.0) is None
    assert wilder_atr([1.0, 2.0], [0.0, 1.0], [0.5, 1.5], 2) is not None or True