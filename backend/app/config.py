"""Configuration management for the Fibonacci MT5 Bot.

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
    app_name: str = Field(default="Fibonacci MT5 Bot", description="Application name")
    app_version: str = Field(default="0.1.0", description="Application version")
    app_env: str = Field(default="development", description="Application environment (development/production)")
    app_read_only: bool = True  # APP_READ_ONLY: safety switch, must remain True
    backend_host: str = Field(default="127.0.0.1", description="Backend host")
    backend_port: int = Field(default=8000, ge=1, le=65535, description="Backend port")
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(default="standard", description="Log format (standard/json)")

    # --- MetaTrader 5 Connection Settings ---
    mt5_symbol: str = Field(default="XAUUSD", description="Primary symbol to trade")
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

    # --- Reports Settings ---
    # Empty means "use the project's default reports root"
    # (`app.reports.service.DEFAULT_REPORTS_DIR`, i.e. <repo>/reports/backtests),
    # so the read-only reports API/dashboard scans the directory the
    # historical-simulation CLI actually writes to without extra configuration.
    reports_dir: str = Field(default="", description="Directory for storing reports (empty = project default)")

    # --- Execution / Risk Management Settings ---
    execution_min_stop_distance_points: float = Field(
        default=100.0, ge=0, description="Minimum stop distance in points for execution"
    )
    execution_max_stop_distance_points: float = Field(
        default=5000.0, ge=0, description="Maximum stop distance in points for execution"
    )
    execution_min_reward_risk: Union[float, None] = Field(
        default=None, description="Minimum reward/risk for execution (defaults to strategy value)"
    )
    execution_max_spread_points: float = Field(
        default=50.0, ge=0, description="Maximum spread in points allowed for execution"
    )
    execution_max_price_drift_points: float = Field(
        default=300.0, ge=0,
        description="Maximum price drift in points allowed between the current quote and the setup's primary entry level",
    )
    execution_max_signal_age_minutes: int = Field(
        default=60, ge=0, description="Maximum signal age in minutes allowed"
    )
    execution_max_quote_age_seconds: float = Field(
        default=10.0, gt=0, allow_inf_nan=False, description="Maximum quote age in seconds allowed"
    )
    execution_risk_per_trade_percent: float = Field(
        default=0.5, gt=0, le=100, allow_inf_nan=False,
        description="Risk per trade as percentage of equity"
    )
    execution_max_risk_per_trade_percent: float = Field(
        default=2.0, gt=0, le=100, allow_inf_nan=False, description="Maximum risk per trade as percentage of equity"
    )
    execution_max_aggregate_risk_percent: float = Field(
        default=5.0, ge=0, le=100, description="Maximum aggregate risk as percentage of equity"
    )
    execution_max_open_positions: int = Field(
        default=3, ge=0, description="Maximum open positions allowed"
    )
    execution_max_daily_loss_percent: float = Field(
        default=5.0, gt=0, le=100, allow_inf_nan=False, description="Maximum daily loss as percentage of equity"
    )
    execution_max_daily_drawdown_percent: float = Field(
        default=10.0, gt=0, le=100, allow_inf_nan=False, description="Maximum daily drawdown as percentage of equity"
    )
    execution_max_consecutive_losses: Optional[int] = Field(
        default=None, description="Consecutive-loss circuit breaker (null = disabled)"
    )
    execution_cost_allowance_percent: float = Field(
        default=0.0, ge=0, le=100,
        description="Cost allowance deducted from the per-trade risk budget, as a percentage",
    )
    execution_tp_policy: str = Field(
        default="none", description="Take profit policy (none, fixed_rr, measured_move)"
    )
    execution_fixed_rr: float = Field(
        default=2.0, gt=0, allow_inf_nan=False,
        description="Fixed reward/risk ratio when tp_policy is fixed_rr"
    )
    execution_allowed_symbols: str = Field(
        default="XAUUSD", description="Comma-separated symbols execution may trade"
    )
    execution_allowed_timeframes: str = Field(
        default="M1,M5,M15,M30,H1,H4,D1",
        description="Comma-separated timeframes execution may trade",
    )
    execution_allowed_symbols_list: Optional[List[str]] = Field(
        default=None, description="Explicit override of the allowed-symbol list"
    )
    execution_allowed_timeframes_list: Optional[List[str]] = Field(
        default=None, description="Explicit override of the allowed-timeframe list"
    )
    execution_block_on_external_positions: bool = Field(
        default=False, description="Block execution when external positions exist"
    )
    execution_daily_reset: str = Field(
        default="broker_midnight", description="Daily risk reset timing (utc_midnight or broker_midnight)"
    )
    execution_magic_number: int = Field(
        default=1000, ge=0, description="Magic number for MT5 order identification"
    )
    execution_filling_policy: str = Field(
        default="auto", description="Order filling policy (auto, fok, ioc, return)"
    )
    execution_configured: bool = Field(
        default=False, description="Whether execution is configured and enabled"
    )
    execution_demo_login: Optional[int] = Field(
        default=None, description="Demo login for execution authorization"
    )
    execution_demo_server: Optional[str] = Field(
        default=None, description="Demo server for execution authorization"
    )
    execution_enabled: bool = Field(
        default=False, description="Master switch to enable/disable execution"
    )
    execution_daily_profit_target_usd: float = Field(
        default=10.0, ge=0,
        description="Daily net profit target in account currency; once reached the bot stops accepting new entries (a stop-entry threshold, never a promise of income)",
    )
    execution_max_entries_per_day: int = Field(
        default=4, ge=0,
        description="Maximum new entries per risk day (0 = unlimited)",
    )

    # --- Credential-display safety ---
    expose_account_login: bool = Field(
        default=False,
        description="Expose the raw account login instead of masking it (trusted local machines only)",
    )

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
            # Execution summary: booleans only, never the raw identity
            "execution_enabled": self.execution_enabled,
            "execution_demo_login_configured": self.execution_demo_login is not None,
            "execution_demo_server_configured": bool(self.execution_demo_server),
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
        """Cross-validate generic application settings (non-strategy)."""
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

    @model_validator(mode="after")
    def validate_execution_settings(self) -> "Settings":
        """Execution safety: consistent limits, valid scope, explicit identity.

        Inconsistent risk configuration refuses to start (it is never silently
        clamped), and every error names the environment variable so the
        operator can fix it directly.
        """
        # --- explicit demo identity is mandatory before execution can be enabled
        if self.execution_enabled and self.execution_demo_login is None:
            raise ValueError(
                "EXECUTION_DEMO_LOGIN is required when EXECUTION_ENABLED is set"
            )
        if self.execution_enabled and self.execution_demo_server is None:
            raise ValueError(
                "EXECUTION_DEMO_SERVER is required when EXECUTION_ENABLED is set"
            )

        # --- risk limits must be internally consistent (rejected, not clamped)
        if self.execution_risk_per_trade_percent > self.execution_max_risk_per_trade_percent:
            raise ValueError(
                "EXECUTION_RISK_PER_TRADE_PERCENT must not exceed "
                "EXECUTION_MAX_RISK_PER_TRADE_PERCENT"
            )
        if self.execution_max_daily_loss_percent > self.execution_max_daily_drawdown_percent:
            raise ValueError(
                "EXECUTION_MAX_DAILY_LOSS_PERCENT must not exceed "
                "EXECUTION_MAX_DAILY_DRAWDOWN_PERCENT"
            )
        if self.execution_min_stop_distance_points > self.execution_max_stop_distance_points:
            raise ValueError(
                "EXECUTION_MIN_STOP_DISTANCE_POINTS must not exceed "
                "EXECUTION_MAX_STOP_DISTANCE_POINTS"
            )

        # --- allowed scope: string form and explicit list must agree ----------
        provided = self.model_fields_set
        if "execution_allowed_symbols_list" in provided:
            symbols = [s.strip() for s in (self.execution_allowed_symbols_list or []) if str(s).strip()]
            if not symbols:
                raise ValueError("EXECUTION_ALLOWED_SYMBOLS must list at least one symbol")
            self.execution_allowed_symbols_list = symbols
        else:
            symbols = [
                s.strip()
                for s in (self.execution_allowed_symbols or "").split(",")
                if s.strip()
            ]
            if not symbols:
                raise ValueError("EXECUTION_ALLOWED_SYMBOLS must list at least one symbol")
            self.execution_allowed_symbols_list = symbols

        if "execution_allowed_timeframes_list" in provided:
            timeframes = [
                tf.strip().upper()
                for tf in (self.execution_allowed_timeframes_list or [])
                if str(tf).strip()
            ]
        else:
            timeframes = [
                tf.strip().upper()
                for tf in (self.execution_allowed_timeframes or "").split(",")
                if tf.strip()
            ]
        if not timeframes:
            raise ValueError("EXECUTION_ALLOWED_TIMEFRAMES must list at least one timeframe")
        from app.mt5.timeframes import SUPPORTED_TIMEFRAMES

        unsupported = [tf for tf in timeframes if tf not in set(SUPPORTED_TIMEFRAMES)]
        if unsupported:
            raise ValueError(
                "EXECUTION_ALLOWED_TIMEFRAMES contains unsupported timeframes: "
                + ", ".join(unsupported)
                + "; supported are "
                + ", ".join(SUPPORTED_TIMEFRAMES)
            )
        self.execution_allowed_timeframes_list = timeframes

        # --- readiness flag (derived, never trusted from the environment) -----
        self.execution_configured = bool(
            self.execution_enabled
            and self.execution_demo_login is not None
            and (self.execution_demo_server or "").strip()
        )

        return self


# Global settings instance and management functions
_settings_cache: Optional[Settings] = None


def get_settings() -> Settings:
    """Get the cached settings instance."""
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = Settings()
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
            error_messages.append(f"  - {field_name}: {error_type}")
        
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


def build_settings(**overrides) -> Settings:
    """Build settings instance without caching (primarily for testing).
    
    This function creates a new Settings instance without affecting the global cache.
    """
    return Settings(_env_file=None, **overrides)


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
    "build_settings",
]