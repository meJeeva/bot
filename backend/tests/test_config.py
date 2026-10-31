"""Configuration validation.

Covers: valid and invalid configuration, the read-only safety switch,
credential hygiene and derived helpers.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import (
    ConfigurationError,
    Settings,
    get_settings,
    load_settings,
    reset_settings_cache,
)


def build(**overrides) -> Settings:
    overrides.setdefault("database_enabled", False)
    return Settings(_env_file=None, **overrides)


class TestValidConfiguration:
    def test_defaults_are_valid_and_read_only_safe(self):
        settings = build()

        assert settings.app_read_only is True
        assert settings.backend_host == "127.0.0.1"
        assert settings.mt5_symbol == "XAUUSD"
        assert settings.poll_interval_ms == 1000
        assert settings.stale_tick_threshold_seconds > 0

    def test_allowed_origins_parsed_into_list(self):
        settings = build(allowed_origins="http://localhost:5173, http://127.0.0.1:5173 ,")
        assert settings.allowed_origins_list == [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]

    def test_symbol_candidates_are_ordered_and_deduplicated(self):
        settings = build(mt5_symbol_candidates="XAUUSD, XAUUSDm , XAUUSD, #XAUUSD")
        assert settings.symbol_candidates == ["XAUUSD", "XAUUSDm", "#XAUUSD"]

    def test_derived_timing_helpers(self):
        settings = build(poll_interval_ms=2500, ws_push_interval_ms=500)
        assert settings.poll_interval_seconds == 2.5
        assert settings.ws_push_interval_seconds == 0.5


class TestRejectedConfiguration:
    def test_read_only_must_never_be_disabled(self):
        with pytest.raises(ValidationError) as info:
            build(app_read_only=False)
        assert "APP_READ_ONLY" in str(info.value)

    def test_candle_limit_may_not_exceed_max(self):
        with pytest.raises(ValidationError) as info:
            build(candle_limit=600, max_candle_limit=500)
        assert "MAX_CANDLE_LIMIT" in str(info.value)

    def test_reconnect_delay_ordering_is_enforced(self):
        with pytest.raises(ValidationError) as info:
            build(
                reconnect_initial_delay_seconds=30,
                reconnect_max_delay_seconds=5,
            )
        assert "RECONNECT_MAX_DELAY_SECONDS" in str(info.value)

    def test_empty_allowed_origins_is_rejected(self):
        with pytest.raises(ValidationError):
            build(allowed_origins="   ")

    def test_wildcard_origin_rejected_in_production(self):
        with pytest.raises(ValidationError) as info:
            build(app_env="production", allowed_origins="*")
        assert "wildcard" in str(info.value).lower()

    def test_wildcard_origin_allowed_in_development(self):
        settings = build(app_env="development", allowed_origins="*")
        assert settings.allowed_origins_list == ["*"]

    def test_empty_symbol_is_rejected(self):
        with pytest.raises(ValidationError):
            build(mt5_symbol="   ")

    def test_port_range_is_validated(self):
        with pytest.raises(ValidationError):
            build(backend_port=70000)
        with pytest.raises(ValidationError):
            build(backend_port=0)

    def test_password_without_login_is_rejected(self):
        with pytest.raises(ValidationError) as info:
            build(mt5_password="secret", mt5_login=None)
        assert "MT5_LOGIN" in str(info.value)

    def test_missing_terminal_path_is_rejected(self, tmp_path):
        missing = tmp_path / "nope" / "terminal64.exe"
        with pytest.raises(ValidationError) as info:
            build(mt5_terminal_path=str(missing))
        assert "MT5_TERMINAL_PATH" in str(info.value)

    def test_terminal_directory_without_executable_is_rejected(self, tmp_path):
        with pytest.raises(ValidationError) as info:
            build(mt5_terminal_path=str(tmp_path))
        assert "terminal64.exe" in str(info.value)

    def test_valid_terminal_directory_is_accepted(self, tmp_path):
        (tmp_path / "terminal64.exe").write_text("stub", encoding="utf-8")
        settings = build(mt5_terminal_path=str(tmp_path))
        assert settings.mt5_terminal_path == str(tmp_path)


class TestEnvironmentLoading:
    def test_reads_values_from_environment(self, monkeypatch):
        monkeypatch.setenv("MT5_SYMBOL", "XAUUSDm")
        monkeypatch.setenv("POLL_INTERVAL_MS", "2500")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        settings = Settings(_env_file=None)

        assert settings.mt5_symbol == "XAUUSDm"
        assert settings.poll_interval_ms == 2500
        assert settings.log_level == "DEBUG"

    def test_blank_optional_values_become_none(self):
        settings = build(mt5_terminal_path="", mt5_server="")
        assert settings.mt5_terminal_path is None
        assert settings.mt5_server is None

    def test_load_settings_raises_configuration_error_with_guidance(self):
        with pytest.raises(ConfigurationError) as info:
            load_settings(app_read_only=False)

        message = str(info.value)
        assert "Invalid application configuration" in message
        assert "APP_READ_ONLY" in message
        assert ".env" in message

    def test_get_settings_reports_a_bad_terminal_path_with_guidance(
        self, monkeypatch, tmp_path
    ):
        """A missing terminal must fail with guidance, not a raw traceback."""
        monkeypatch.setenv(
            "MT5_TERMINAL_PATH", str(tmp_path / "nope" / "terminal64.exe")
        )
        reset_settings_cache()
        try:
            with pytest.raises(ConfigurationError) as info:
                get_settings()

            message = str(info.value)
            assert "Invalid application configuration" in message
            assert "MT5_TERMINAL_PATH" in message
        finally:
            reset_settings_cache()

    def test_get_settings_is_cached_and_resettable(self, monkeypatch):
        monkeypatch.setenv("MT5_SYMBOL", "XAUUSD")
        monkeypatch.setenv("MT5_LOGIN", "12345")
        reset_settings_cache()
        first = get_settings()
        assert get_settings() is first

        reset_settings_cache()
        assert get_settings() is not first


class TestSecretHygiene:
    def test_safe_summary_never_exposes_credentials(self):
        settings = build(
            mt5_login=5057247615,
            mt5_password="top-secret-value",
            mt5_server="MetaQuotes-Demo",
        )
        summary = settings.safe_summary()
        rendered = repr(summary)

        assert "top-secret-value" not in rendered
        assert "5057247615" not in rendered
        assert summary["mt5_credentials_supplied"] is True

    def test_safe_summary_contains_expected_operational_keys(self):
        summary = build().safe_summary()

        for key in (
            "app_env",
            "backend_host",
            "backend_port",
            "allowed_origins",
            "mt5_symbol",
            "poll_interval_ms",
            "candle_limit",
            "stale_tick_threshold_seconds",
            "log_level",
            "app_read_only",
        ):
            assert key in summary
