"""Regression tests for profile-specific lot sizes."""

from __future__ import annotations

from app.config import Settings


def test_xauusd_resolves_configured_lot_size():
    settings = Settings(
        _env_file=None,
        AUTO_TRADE_PROFILE="XAUUSD",
        XAUUSD_LOT_SIZE=0.36,
    )
    assert settings.auto_trade_profile == "XAUUSD"
    assert settings.auto_trade_lot_size == 0.36
    assert settings.xauusd_lot_size == 0.36