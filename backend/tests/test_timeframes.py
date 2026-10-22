"""The central seven-timeframe mapping."""

from __future__ import annotations

import pytest

from app.mt5.timeframes import (
    SUPPORTED_TIMEFRAMES,
    TIMEFRAME_ORDER,
    TIMEFRAMES,
    UnsupportedTimeframeError,
    get_timeframe,
    normalize_timeframe,
)

# Documented MetaQuotes constants. Asserting them pins the mapping to the
# published API rather than to whatever the installed wheel happens to expose.
EXPECTED_MT5_VALUES = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 16385,
    "H4": 16388,
    "D1": 16408,
}

EXPECTED_SECONDS = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}


class TestTimeframeSet:
    def test_exactly_seven_timeframes_exist(self):
        assert len(SUPPORTED_TIMEFRAMES) == 7
        assert SUPPORTED_TIMEFRAMES == ("M1", "M5", "M15", "M30", "H1", "H4", "D1")
        assert TIMEFRAME_ORDER == SUPPORTED_TIMEFRAMES

    @pytest.mark.parametrize("name,expected", EXPECTED_MT5_VALUES.items())
    def test_maps_to_the_correct_mt5_constant(self, name, expected):
        assert TIMEFRAMES[name].mt5_value == expected

    @pytest.mark.parametrize("name,expected", EXPECTED_SECONDS.items())
    def test_maps_to_the_correct_duration(self, name, expected):
        assert TIMEFRAMES[name].seconds == expected

    def test_every_timeframe_has_a_human_label(self):
        for name, spec in TIMEFRAMES.items():
            assert spec.label
            assert spec.name == name


class TestNormalization:
    @pytest.mark.parametrize(
        "raw",
        ["M15", "m15", "  m15  ", "TIMEFRAME_M15", "timeframe_m15"],
    )
    def test_accepts_supported_names_case_insensitively(self, raw):
        assert normalize_timeframe(raw) == "M15"

    @pytest.mark.parametrize(
        "raw",
        ["", "X1", "M2", "M3", "M10", "H2", "W1", "MN1", "15", "1h", None, 15],
    )
    def test_rejects_anything_outside_the_seven(self, raw):
        with pytest.raises(UnsupportedTimeframeError):
            normalize_timeframe(raw)  # type: ignore[arg-type]

    def test_error_message_lists_the_supported_values(self):
        with pytest.raises(UnsupportedTimeframeError) as info:
            normalize_timeframe("X1")

        message = str(info.value)
        for name in SUPPORTED_TIMEFRAMES:
            assert name in message


class TestLookups:
    def test_get_timeframe_returns_spec(self):
        spec = get_timeframe("h4")
        assert spec.name == "H4"
        assert spec.mt5_value == 16388
        assert spec.duration_seconds == 14400
