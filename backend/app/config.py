"""Configuration management for the read-only MT5 market-data application.

Loads settings from environment variables with validation and provides
access to configuration values throughout the application.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Tuple, Union

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(RuntimeError):
    """Raised when configuration validation fails with user guidance."""


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Core Application Settings ---
    app_name: str = Field(default="MT5 Market Data", description="Application name")
    app_version: str = Field(default="0.1.0", description="Application version")
    app_env: str = Field(default="development", description="Application environment (development/production)")
    app_read_only: bool = True  # APP_READ_ONLY: safety switch, must remain True
    backend_host: str = Field(default="127.0.0.1", description="Backend host")
    backend_port: int = Field(default=8000, ge=1, le=65535, description="Backend port")
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(default="standard", description="Log format (standard/json)")

    # --- MetaTrader 5 Connection Settings ---
    mt5_symbol: str = Field(default="XAUUSD", description="Primary symbol to read")
    mt5_symbol_candidates: str = Field(
        default="XAUUSD,XAUUSD.,XAUUSDm,XAUUSD.c,#XAUUSD",
        description="Comma-separated list of symbol candidates for discovery"
    )
    mt5_symbol_strict: bool = Field(default=False, description="Strict symbol matching")
    mt5_login: Optional[int] = Field(default=None, description="MT5 login ID (for unattended operation)")
    mt5_password: Optional[str] = Field(default=None, description="MT5 password (for unattended operation)")
    mt5_server: Optional[str] = Field(default=None, description="MT5 server (for unattended operation)")
    mt5_terminal_path: Optional[str] = Field(default=None, description="Path to MT5 terminal64.exe")
    mt5_timeout_ms: int = Field(default=60000, description="MT5 connection timeout in milliseconds")
    poll_interval_ms: int = Field(default=1000, description="Polling interval for market data in milliseconds")
    stale_tick_threshold_seconds: int = Field(default=20, description="Seconds after which a tick is considered stale")
    
    # --- Reconnection Settings ---
    reconnect_initial_delay_seconds: float = Field(
        default=2.0, ge=0, description="Initial reconnection delay in seconds"
    )
    reconnect_max_delay_seconds: float = Field(
        default=60.0, ge=0, description="Maximum reconnection delay in seconds"
    )
    reconnect_max_attempts: int = Field(
        default=0, ge=0, description="Maximum reconnection attempts (0 = infinite)"
    )

    # --- WebSocket Settings ---
    ws_max_queue: int = Field(default=8, description="Maximum WebSocket queue size per client")
    ws_push_interval_ms: int = Field(default=500, description="WebSocket push interval in milliseconds")
    ws_heartbeat_seconds: int = Field(default=30, description="WebSocket heartbeat interval in seconds")

    # --- Candle Data Settings ---
    candle_limit: int = Field(default=300, ge=1, le=5000, description="Default candle limit for API requests")
    max_candle_limit: int = Field(default=5000, ge=1, description="Maximum allowed candle limit")
    candle_refresh_seconds: int = Field(default=300, description="Seconds between candle history refreshes")
    select_symbol_in_market_watch: bool = Field(
        default=True,
        description="Whether to select discovered symbol in Market Watch"
    )
    allowed_origins: str = Field(
        default="http://localhost:5173",
        description="Comma-separated list of allowed CORS origins"
    )

    # --- Database Settings ---
    database_enabled: bool = Field(default=True, description="Enable SQLite database for persistence")
    database_path: Optional[str] = Field(
        default=None,
        description="SQLite database file. Empty uses the default runtime location.",
    )

    # --- Credential-display safety ---
    expose_account_login: bool = Field(
        default=False,
        description="Expose the raw account login instead of masking it (trusted local machines only)",
    )

    # --- Automatic trading settings (5-second cycle) ---
    auto_trade_magic_number: int = Field(default=9001, description="Magic number for the automatic trading strategy")
    auto_trade_volume: float = Field(default=0.01, gt=0, description="Configured order volume for the automatic trading strategy")
    auto_trade_max_spread_points: float = Field(default=100.0, ge=0, description="Maximum permitted spread in points")
    auto_trade_max_entry_deviation_points: int = Field(default=20, ge=0, description="Maximum allowed entry price deviation in points")
    auto_trade_max_daily_loss: float = Field(default=100.0, ge=0, description="Maximum permitted daily loss")
    auto_trade_max_cycles: int = Field(default=1000, ge=1, description="Maximum number of cycles per session")
    auto_trade_entry_interval_seconds: int = Field(default=5, ge=1, le=300, description="Interval between BUY entries in seconds")
    auto_trade_holding_duration_seconds: int = Field(default=3, ge=1, le=60, description="Holding duration after confirmed fill in seconds")
    auto_trade_stop_policy: str = Field(default="close", description="Stop policy: close or leave")
    auto_trade_max_retries: int = Field(default=3, ge=0, le=10, description="Bounded retries for transient failures")

    # --- Strict demo-only trading protection ---
    auto_trade_demo_only: bool = Field(default=True, description="Restrict automatic trading to demo accounts only")
    auto_trade_demo_authorized: bool = Field(default=False, description="Explicit authorization for demo trading")
    live_trading_enabled: bool = Field(default=False, description="Allow live trading (must remain false)")

    # --- M1 Trend Pullback Scalping strategy (disabled by default) ---
    trend_pullback_enabled: bool = Field(default=False, description="Enable the M1 trend pullback scalping strategy")
    trend_pullback_symbols: str = Field(default="XAUUSD", description="Comma-separated symbols enabled for trend pullback")
    trend_pullback_entry_timeframe: str = Field(default="M1", description="Entry timeframe for trend pullback")
    trend_pullback_trend_timeframe: str = Field(default="M5", description="Trend timeframe for trend pullback")
    trend_pullback_fast_ema: int = Field(default=20, ge=1, description="Fast EMA period")
    trend_pullback_slow_ema: int = Field(default=50, ge=2, description="Slow EMA period")
    trend_pullback_atr_period: int = Field(default=14, ge=1, description="ATR period")
    trend_pullback_lookback: int = Field(default=5, ge=1, le=5, description="Pullback lookback candles")
    trend_pullback_ema_tolerance_atr: float = Field(default=0.15, ge=0, description="EMA pullback tolerance in ATR units")
    trend_pullback_entry_buffer_points: float = Field(default=5.0, ge=0, description="Entry trigger buffer in points")
    trend_pullback_sl_buffer_points: float = Field(default=5.0, ge=0, description="Stop loss buffer in points")
    trend_pullback_signal_expiry_candles: int = Field(default=2, ge=1, description="Signal expiration in completed M1 candles")
    trend_pullback_min_candle_atr: float = Field(default=0.3, ge=0, description="Minimum confirmation candle size in ATR units")
    trend_pullback_max_candle_atr: float = Field(default=2.0, ge=0, description="Maximum confirmation candle size in ATR units")
    trend_pullback_max_spread_points: float = Field(default=100.0, ge=0, description="Maximum spread in points for trend pullback entries")
    trend_pullback_max_spread_atr_ratio: float = Field(default=0.35, ge=0, description="Maximum spread as ratio of ATR")
    trend_pullback_stale_tick_seconds: int = Field(default=20, ge=1, description="Maximum tick age in seconds")

    # --- Trend Pullback position management ---
    trend_pullback_be_enabled: bool = Field(default=False, description="Enable break-even management for trend pullback")
    trend_pullback_be_atr_multiplier: float = Field(default=0.6, ge=0, description="Break-even ATR multiplier")
    trend_pullback_be_min_spread_multiplier: float = Field(default=2.0, ge=0, description="Minimum spread multiplier for BE")
    trend_pullback_be_buffer_points: float = Field(default=5.0, ge=0, description="Break-even protective buffer in points")
    trend_pullback_trailing_enabled: bool = Field(default=False, description="Enable ATR trailing for trend pullback")
    trend_pullback_trailing_atr_period: int = Field(default=14, ge=1, description="Trailing ATR period")
    trend_pullback_trailing_atr_multiplier: float = Field(default=0.8, ge=0, description="Trailing ATR multiplier")
    trend_pullback_trailing_min_distance_points: float = Field(default=10.0, ge=0, description="Minimum trailing distance in points")
    # --- Computed Fields ---
    @property
    def allowed_origins_list(self) -> List[str]:
        """Parse allowed_origins comma-separated string into a list."""
        if not self.allowed_origins:
            return []
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def poll_interval_seconds(self) -> float:
        """Convert poll_interval_ms to seconds."""
        return self.poll_interval_ms / 1000.0

    @property
    def ws_push_interval_seconds(self) -> float:
        """Convert ws_push_interval_ms to seconds."""
        return self.ws_push_interval_ms / 1000.0

    @property
    def symbol_candidates(self) -> List[str]:
        """Parse mt5_symbol_candidates comma-separated string into a list.
        
        Preserves original case and format while trimming whitespace and
        removing duplicates while preserving order.
        """
        if not self.mt5_symbol_candidates:
            return ["XAUUSD"]
        candidates = [
            candidate.strip()
            for candidate in self.mt5_symbol_candidates.split(",")
            if candidate.strip()
        ]
        # Remove duplicates while preserving order
        seen = set()
        result = []
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                result.append(candidate)
        return result

    @property
    def trend_pullback_symbols_list(self) -> List[str]:
        if not self.trend_pullback_symbols:
            return []
        return [s.strip().upper() for s in self.trend_pullback_symbols.split(",") if s.strip()]

    @property
    def mt5_credentials_supplied(self) -> bool:
        """Check if MT5 credentials are supplied for unattended operation."""
        return (
            self.mt5_login is not None
            and self.mt5_password is not None
            and self.mt5_server is not None
        )

    def safe_summary(self) -> dict:
        """Return a safe summary of settings with credentials masked."""
        return {
            "app_env": self.app_env,
            "app_name": self.app_name,
            "app_version": self.app_version,
            "backend_host": self.backend_host,
            "backend_port": self.backend_port,
            "log_level": self.log_level,
            "database_enabled": self.database_enabled,
            "mt5_symbol": self.mt5_symbol,
            "poll_interval_ms": self.poll_interval_ms,
            "stale_tick_threshold_seconds": self.stale_tick_threshold_seconds,
            "candle_limit": self.candle_limit,
            "ws_max_queue": self.ws_max_queue,
            "ws_push_interval_ms": self.ws_push_interval_ms,
            "ws_heartbeat_seconds": self.ws_heartbeat_seconds,
            "app_read_only": self.app_read_only,
            "mt5_credentials_supplied": self.mt5_credentials_supplied,
            "allowed_origins": self.allowed_origins,
        }

    # --- Validators ---
    @field_validator("mt5_terminal_path", mode="before")
    @classmethod
    def validate_mt5_terminal_path(cls, v):
        """Validate MT5 terminal path - must be None or a directory containing terminal64.exe."""
        if v is None:
            return v
        # Handle empty strings - convert to None
        if not isinstance(v, str):
            return v
        if not v.strip():
            return None
        # Two forms are valid: the install directory (which must contain
        # terminal64.exe) and a direct path to that executable - the form
        # terminal discovery produces. Anything else is refused here rather
        # than handed to MetaTrader5.initialize.
        if os.path.isfile(v):
            if os.path.splitext(v)[1].lower() != ".exe":
                raise ValueError(
                    f"MT5_TERMINAL_PATH must point at terminal64.exe: {v}"
                )
            return v
        if os.path.isdir(v):
            if not os.path.isfile(os.path.join(v, "terminal64.exe")):
                raise ValueError(
                    f"MT5_TERMINAL_PATH must be a directory containing terminal64.exe (not found in {v})"
                )
            return v
        raise ValueError(f"MT5_TERMINAL_PATH does not exist: {v}")

    @field_validator("mt5_password")
    @classmethod
    def validate_mt5_password(cls, v: Optional[str]) -> Optional[str]:
        """Validate MT5 password - empty strings become None."""
        if v is not None:
            if not isinstance(v, str):
                return v
            if not v.strip():
                return None
        return v

    @field_validator("mt5_server")
    @classmethod
    def validate_mt5_server(cls, v: Optional[str]) -> Optional[str]:
        """Validate MT5 server - empty strings become None."""
        if v is not None:
            if not isinstance(v, str):
                return v
            if not v.strip():
                return None
        return v

    @field_validator("mt5_login", mode="before")
    @classmethod
    def validate_mt5_login(cls, v):
        """Validate MT5 login - empty strings become None."""
        if v is not None:
            if isinstance(v, str):
                if not v.strip():
                    return None
                try:
                    return int(v)
                except ValueError:
                    raise ValueError("MT5_LOGIN must be a valid integer")
        return v

    @field_validator("auto_trade_stop_policy", mode="before")
    @classmethod
    def validate_auto_trade_stop_policy(cls, v):
        """Normalise the Stop policy; only 'close' and 'leave' are meaningful."""
        if v is None:
            return "close"
        if not isinstance(v, str):
            return v
        policy = v.strip().lower()
        if not policy:
            return "close"
        if policy not in ("close", "leave"):
            raise ValueError("AUTO_TRADE_STOP_POLICY must be 'close' or 'leave'")
        return policy

    @field_validator("mt5_symbol")
    @classmethod
    def validate_mt5_symbol(cls, v: str) -> str:
        """Ensure MT5 symbol is not empty or just whitespace."""
        if not v or not v.strip():
            raise ValueError("MT5_SYMBOL must not be empty")
        return v.strip()

    @field_validator("mt5_symbol_candidates")
    @classmethod
    def validate_mt5_symbol_candidates(cls, v: str) -> str:
        """Ensure MT5 symbol candidates string is valid."""
        if not v:
            return "XAUUSD"
        # Basic validation - just ensure it's not empty
        return v.strip()

    @field_validator("allowed_origins")
    @classmethod
    def validate_allowed_origins(cls, v: Optional[str]) -> Optional[str]:
        """Validate allowed origins format.
        
        - Empty/whitespace-only strings raise an error
        - Wildcard origins are rejected (validation happens in model_validator for app_env)
        """
        if v is None:
            return v
        if not v.strip():
            raise ValueError("ALLOWED_ORIGINS must not be empty or just whitespace")
        # Check for wildcard - will be rejected in model_validator for production
        return v.strip()

    @model_validator(mode="after")
    def validate_application_settings(self) -> "Settings":
        """Cross-validate application settings."""
        # Reconnect delay validation
        if (
            self.reconnect_max_delay_seconds
            < self.reconnect_initial_delay_seconds
        ):
            raise ValueError(
                "RECONNECT_MAX_DELAY_SECONDS must be greater than or equal to "
                "RECONNECT_INITIAL_DELAY_SECONDS"
            )

        # Candle limit validation
        if self.candle_limit > self.max_candle_limit:
            raise ValueError(
                "CANDLE_LIMIT must not exceed MAX_CANDLE_LIMIT"
            )

        # Wildcard origin validation
        if self.allowed_origins == "*":
            if self.app_env == "production":
                raise ValueError(
                    "Wildcard origin '*' is not permitted in production. "
                    "Set ALLOWED_ORIGINS to specific URLs."
                )

        # MT5 credentials: password requires login and server
        if self.mt5_password is not None and self.mt5_login is None:
            raise ValueError(
                "MT5_LOGIN is required when MT5_PASSWORD is set"
            )
        if self.mt5_password is not None and self.mt5_server is None:
            raise ValueError(
                "MT5_SERVER is required when MT5_PASSWORD is set"
            )

        # Read-only safety check
        if not self.app_read_only:
            raise ValueError("APP_READ_ONLY must remain True for safety")

        return self

# Global settings instance and management functions
_settings_cache: Optional[Settings] = None


def get_settings() -> Settings:
    """Get the cached settings instance.

    Invalid configuration raises :class:`ConfigurationError` with guidance
    instead of a raw validation traceback, so a misconfigured deployment
    fails with an actionable message.
    """
    global _settings_cache
    if _settings_cache is None:
        load_settings()
    return _settings_cache


def load_settings(**overrides) -> Settings:
    """Load settings with optional overrides (primarily for testing).
    
    Raises ConfigurationError when validation fails, with guidance on how to fix.
    """
    global _settings_cache
    
    try:
        _settings_cache = Settings(**overrides)
    except ValidationError as e:
        # Format guidance for common errors
        guidance_parts = [
            "Invalid application configuration detected.",
            "Please check the following:",
            "  - Ensure .env file is present in the project root directory",
            "  - Validate environment variable names (should be UPPER_SNAKE_CASE)",
            "  - Verify settings types and values (e.g., numeric ranges, boolean flags)",
            "  - Check safety settings are correctly configured (e.g., APP_READ_ONLY=True)",
        ]
        
        # Highlight specific errors in guidance
        error_messages = []
        for error in e.errors():
            loc = error.get("loc", ())
            field_name = loc[0] if loc else "?"
            error_type = error.get("type", "?")
            detail = error.get("msg", "")
            # The validator messages name the environment variable that has to
            # change, which is what the operator actually edits.
            error_messages.append(f"  - {field_name}: {error_type} ({detail})")
        
        # Add specific field guidance based on error type
        if "APP_READ_ONLY" in str(e):
            guidance_parts.append("  - APP_READ_ONLY must remain True for safety")
        
        # Create ConfigurationError with guidance
        detailed_error = ConfigurationError(
            "\n".join(guidance_parts) + f"\n\nValidation details:\n" + "\n".join(error_messages)
        )
        detailed_error.__cause__ = e  # Preserve original ValidationError as cause
        raise detailed_error
    
    return _settings_cache


def reset_settings_cache() -> None:
    """Reset the cached settings instance (primarily for testing)."""
    global _settings_cache
    _settings_cache = None


# Project root constant
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent


# For backward compatibility with existing code
Settings = Settings  # noqa: F811


__all__ = [
    "PROJECT_ROOT",
    "Settings",
    "ConfigurationError",
    "get_settings",
    "load_settings",
    "reset_settings_cache",
]