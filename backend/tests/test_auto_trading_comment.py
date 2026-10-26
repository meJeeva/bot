"""MT5 order comments for the automatic-trading strategy."""

from __future__ import annotations

import pytest

from app.services.auto_trading import _make_comment


def test_comment_format_function():
    assert _make_comment("AU_M1_B", 1) == "AU_M1_B1"
    assert _make_comment("AU_M1_S", 99) == "AU_M1_S99"
    for i in [1, 10, 100, 1000, 9999, 99999]:
        assert len(_make_comment("AU_M1_B", i)) <= 31
        assert len(_make_comment("AU_M1_S", i)) <= 31