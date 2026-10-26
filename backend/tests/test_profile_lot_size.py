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


def test_btcusd_uses_its_own_profile_volume():
    settings = Settings(
        _env_file=None,
        AUTO_TRADE_PROFILE="BTCUSD",
        MT5_SYMBOL="BTCUSD",
        BTCUSD_ENTRY_OFFSET=15.0,
        BTCUSD_BREAK_EVEN_OFFSET=4.0,
        BTCUSD_TRAILING_DISTANCE=4.0,
        BTCUSD_LOT_SIZE=1.0,
    )
    assert settings.auto_trade_profile == "BTCUSD"
    assert settings.auto_trade_lot_size == 1.0
    assert settings.btcusd_lot_size == 1.0