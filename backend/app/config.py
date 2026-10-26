"""Configuration management for the read-only MT5 market-data application.

Loads settings from environment variables with validation and provides
access to configuration values throughout the application.
"""

from __future__ import annotations

import math
import os
import logging
from pathlib import Path
from typing import List, Optional, Tuple, Union

from pydantic import AliasChoices, Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

#: Established per-instrument values. The XAUUSD column is the original
#: strategy configuration; the BTCUSD column migrates the operator's existing
#: BTCUSD environment values without changing their meanings.
_PROFILE_DEFAULTS: dict[str, dict[str, object]] = {
    "XAUUSD": {
        "symbol": "XAUUSD",
        "symbol_candidates": "XAUUSD,XAUUSD.,XAUUSDm,XAUUSD.c,#XAUUSD",
        "timeframe": "M1",
        "entry_offset": 1.00,
        "break_even_offset": 0.40,
        "trailing_distance": 0.40,
        "lot_size": 0.01,
        "max_spread_points": 100.0,
        "max_entry_deviation_points": 20,
    },
    "BTCUSD": {
        "symbol": "BTCUSD",
        "symbol_candidates": "BTCUSD,BTCUSDm,BTCUSD.c,#BTCUSD,BTCUSD.",
        "timeframe": "M1",
        "entry_offset": 15.0,
        "break_even_offset": 4.0,
        "trailing_distance": 4.0,
        "lot_size": 1.0,
        "max_spread_points": 100.0,
        "max_entry_deviation_points": 20,
    },
}

_LEGACY_PARAM_FIELDS: dict[str, str] = {
    "symbol_candidates": "mt5_symbol_candidates",
    "timeframe": "auto_trade_timeframe",
    "entry_offset": "auto_trade_entry_offset",
    "break_even_offset": "auto_trade_break_even_offset",
    "trailing_distance": "auto_trade_trailing_distance",
    "lot_size": "auto_trade_lot_size",
    "max_spread_points": "auto_trade_max_spread_points",
    "max_entry_deviation_points": "auto_trade_max_entry_deviation_points",
}


class ConfigurationError(RuntimeError):
    """Raised when configuration validation fails with user guidance."""


def _env_file_value(key: str) -> str | None:
    """The value of one key in the configured .env file, or ``None``."""
    try:
        env_file = Path(os.environ.get("DOTENV_PATH", ".env"))
        if not env_file.is_file():
            return None
        wanted = key.upper()
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip().upper() == wanted:
                return value.strip().strip('"').strip("'")
    except OSError:
        return None
    return None


def _same_param(name: str, legacy: object, prefixed: object) -> bool:
    """Whether a legacy and a profile-prefixed value agree for one parameter."""
    if name in (
        "entry_offset",
        "break_even_offset",
        "trailing_distance",
        "lot_size",
        "max_spread_points",
    ):
        try:
            return float(legacy) == float(prefixed)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False
    if name == "max_entry_deviation_points":
        try:
            return int(legacy) == int(prefixed)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False
    return str(legacy).strip() == str(prefixed).strip()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # --- Core Application Settings ---
    app_name: str = Field(default="MT5 Market Data", description="Application name")
    app_version: str = Field(default="0.1.0", description="Application version")
    app_env: str = Field(default="development", description="Application environment (development/production)")
    app_read_only: bool = True
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

    # --- Application/execution safety (common) ---
    trading_mode: str = Field(default="demo", description="Intended execution mode; this build refuses anything but demo")
    auto_trade_demo_authorized: bool = Field(default=False, description="Explicit operator acknowledgment that order placement is authorized on a demo account")

    # --- Instrument profile selection ---
    auto_trade_profile: str = Field(default="XAUUSD", description="Active instrument profile: XAUUSD or BTCUSD")

    # --- XAUUSD profile ---
    xauusd_symbol: Optional[str] = Field(default=None, validation_alias="XAUUSD_MT5_SYMBOL")
    xauusd_symbol_candidates: Optional[str] = Field(default=None, validation_alias="XAUUSD_MT5_SYMBOL_CANDIDATES")
    xauusd_timeframe: Optional[str] = Field(default=None, validation_alias="XAUUSD_TIMEFRAME")
    xauusd_entry_offset: Optional[float] = Field(default=None, validation_alias="XAUUSD_ENTRY_OFFSET")
    xauusd_break_even_offset: Optional[float] = Field(default=None, validation_alias="XAUUSD_BREAK_EVEN_OFFSET")
    xauusd_trailing_distance: Optional[float] = Field(default=None, validation_alias="XAUUSD_TRAILING_DISTANCE")
    xauusd_trailing_mode: Optional[str] = Field(default=None, validation_alias="XAUUSD_TRAILING_MODE")
    xauusd_trail_atr_period: Optional[int] = Field(default=None, validation_alias="XAUUSD_TRAIL_ATR_PERIOD")
    xauusd_trail_atr_multiplier: Optional[float] = Field(default=None, validation_alias="XAUUSD_TRAIL_ATR_MULTIPLIER")
    xauusd_lot_size: Optional[float] = Field(default=None, validation_alias="XAUUSD_LOT_SIZE")
    xauusd_max_spread_points: Optional[float] = Field(default=None, validation_alias="XAUUSD_MAX_SPREAD_POINTS")
    xauusd_max_entry_deviation_points: Optional[int] = Field(default=None, validation_alias="XAUUSD_MAX_ENTRY_DEVIATION_POINTS")

    # --- BTCUSD profile ---
    btcusd_symbol: Optional[str] = Field(default=None, validation_alias="BTCUSD_MT5_SYMBOL")
    btcusd_symbol_candidates: Optional[str] = Field(default=None, validation_alias="BTCUSD_MT5_SYMBOL_CANDIDATES")
    btcusd_timeframe: Optional[str] = Field(default=None, validation_alias="BTCUSD_TIMEFRAME")
    btcusd_entry_offset: Optional[float] = Field(default=None, validation_alias="BTCUSD_ENTRY_OFFSET")
    btcusd_break_even_offset: Optional[float] = Field(default=None, validation_alias="BTCUSD_BREAK_EVEN_OFFSET")
    btcusd_trailing_distance: Optional[float] = Field(default=None, validation_alias="BTCUSD_TRAILING_DISTANCE")
    btcusd_lot_size: Optional[float] = Field(default=None, validation_alias="BTCUSD_LOT_SIZE")
    btcusd_max_spread_points: Optional[float] = Field(default=None, validation_alias="BTCUSD_MAX_SPREAD_POINTS")
    btcusd_max_entry_deviation_points: Optional[int] = Field(default=None, validation_alias="BTCUSD_MAX_ENTRY_DEVIATION_POINTS")

    # --- Automatic trading settings ---
    auto_trade_symbol: Optional[str] = Field(default=None, description="Instrument the strategy trades")
    auto_trade_timeframe: str = Field(default="M1", description="Strategy chart timeframe")
    auto_trade_entry_offset: Optional[float] = Field(default=None, gt=0, description="Entry offset")
    auto_trade_magic_number: int = Field(default=9001, description="Magic number")
    auto_trade_lot_size: float = Field(
        default=0.01, gt=0, validation_alias=AliasChoices("AUTO_TRADE_LOT_SIZE", "AUTO_TRADE_VOLUME"),
        description="Configured fixed lot size"
    )
    auto_trade_break_even_offset: float = Field(default=0.40, gt=0, description="Break-even offset")
    auto_trade_trailing_distance: float = Field(default=0.40, gt=0, description="Trailing distance")
    auto_trade_max_spread_points: float = Field(default=100.0, ge=0, description="Max spread points")
    auto_trade_max_entry_deviation_points: int = Field(default=20, ge=0, description="Max entry deviation points")
    auto_trade_max_daily_loss: float = Field(default=100.0, ge=0, description="Max daily loss")
    auto_trade_max_cycles: int = Field(default=1000, ge=1, description="Max cycles")
    auto_trade_entry_interval_seconds: int = Field(default=5, ge=1, le=300, description="Entry interval")
    auto_trade_holding_duration_seconds: int = Field(default=3, ge=1, le=60, description="Holding duration")
    auto_trade_stop_policy: str = Field(default="close", description="Stop policy")
    auto_trade_max_retries: int = Field(default=3, ge=0, le=10, description="Max retries")
    auto_trade_exit_buffer_seconds: int = Field(default=2, ge=0, le=300, description="Exit buffer seconds")

    # --- Dynamic break-even ---
    be_mode: str = Field(default="static", description="Break-even mode")
    be_atr_period: int = Field(default=14, ge=2, le=200, description="ATR period")
    be_atr_multiplier: float = Field(default=0.6, gt=0, description="ATR multiplier")
    be_min_spread_multiplier: float = Field(default=2.0, ge=0, description="Min spread multiplier")
    be_cost_buffer_per_lot: float = Field(default=0.0, ge=0, description="Cost buffer per lot")

    # --- Performance reporting ---
    report_timezone: str = Field(default="Asia/Kolkata", description="Report timezone")
    performance_max_history_days: int = Field(default=92, ge=1, le=366, description="Max history days")
    performance_cache_seconds: int = Field(default=10, ge=0, le=300, description="Cache seconds")

    # --- Computed properties ---
    @property
    def auto_trade_volume(self) -> float:
        return self.auto_trade_lot_size

    @property
    def allowed_origins_list(self) -> List[str]:
        if not self.allowed_origins:
            return []
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def poll_interval_seconds(self) -> float:
        return self.poll_interval_ms / 1000.0

    @property
    def ws_push_interval_seconds(self) -> float:
        return self.ws_push_interval_ms / 1000.0

    @property
    def symbol_candidates(self) -> List[str]:
        if not self.mt5_symbol_candidates:
            return [self.mt5_symbol or "XAUUSD"]
        candidates = [c.strip() for c in self.mt5_symbol_candidates.split(",") if c.strip()]
        seen = set()
        result = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                result.append(c)
        return result

    @property
    def mt5_credentials_supplied(self) -> bool:
        return self.mt5_login is not None and self.mt5_password is not None and self.mt5_server is not None

    def safe_summary(self) -> dict:
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
        if v is None:
            return v
        if not isinstance(v, str):
            return v
        if not v.strip():
            return None
        if os.path.isfile(v):
            if os.path.splitext(v)[1].lower() != ".exe":
                raise ValueError(f"MT5_TERMINAL_PATH must point at terminal64.exe: {v}")
            return v
        if os.path.isdir(v):
            if not os.path.isfile(os.path.join(v, "terminal64.exe")):
                raise ValueError(f"MT5_TERMINAL_PATH must be a directory containing terminal64.exe (not found in {v})")
            return v
        raise ValueError(f"MT5_TERMINAL_PATH does not exist: {v}")

    @field_validator("mt5_password")
    @classmethod
    def validate_mt5_password(cls, v):
        if v is not None and isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("mt5_server")
    @classmethod
    def validate_mt5_server(cls, v):
        if v is not None and isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("mt5_login", mode="before")
    @classmethod
    def validate_mt5_login(cls, v):
        if v is not None and isinstance(v, str):
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
    def validate_mt5_symbol(cls, v):
        if not v or not str(v).strip():
            raise ValueError("MT5_SYMBOL must not be empty")
        return str(v).strip()

    @field_validator("mt5_symbol_candidates")
    @classmethod
    def validate_mt5_symbol_candidates(cls, v):
        if not v:
            return "XAUUSD"
        return str(v).strip()

    @field_validator("be_mode")
    @classmethod
    def validate_be_mode(cls, v):
        mode = (v or "").strip().lower()
        if mode not in ("static", "atr"):
            raise ValueError(f"BE_MODE must be 'static' or 'atr'; received {v!r}")
        return mode

    @field_validator("trading_mode")
    @classmethod
    def validate_trading_mode(cls, v):
        mode = (v or "").strip().lower()
        if mode != "demo":
            raise ValueError(f"TRADING_MODE: this build supports demo execution only; received {v!r}")
        return mode

    @field_validator("auto_trade_timeframe")
    @classmethod
    def validate_auto_trade_timeframe(cls, v):
        if v is None:
            return v
        timeframe = str(v).strip().upper()
        if timeframe != "M1":
            raise ValueError(f"AUTO_TRADE_TIMEFRAME: this static strategy runs on M1 only; received {v!r}")
        return timeframe

    @field_validator("allowed_origins")
    @classmethod
    def validate_allowed_origins(cls, v):
        if v is None:
            return v
        if not str(v).strip():
            raise ValueError("ALLOWED_ORIGINS must not be empty or just whitespace")
        return str(v).strip()

    @field_validator("auto_trade_profile", mode="before")
    @classmethod
    def validate_auto_trade_profile(cls, v):
        if v is None:
            return "XAUUSD"
        if not isinstance(v, str):
            return v
        profile = v.strip().upper()
        if not profile:
            return "XAUUSD"
        if profile not in _PROFILE_DEFAULTS:
            raise ValueError(f"AUTO_TRADE_PROFILE must be one of {sorted(_PROFILE_DEFAULTS)}; received {v!r}")
        return profile

    @field_validator(
        "auto_trade_lot_size",
        "auto_trade_break_even_offset",
        "auto_trade_trailing_distance",
        "xauusd_entry_offset",
        "xauusd_break_even_offset",
        "xauusd_trailing_distance",
        "xauusd_lot_size",
        "btcusd_entry_offset",
        "btcusd_break_even_offset",
        "btcusd_trailing_distance",
        "btcusd_lot_size",
        mode="before",
    )
    @classmethod
    def _validate_finite_positive(cls, v):
        if v is None:
            return v
        try:
            value = float(v)
        except (TypeError, ValueError) as exc:
            raise ValueError("must be a finite number") from exc
        if not math.isfinite(value):
            raise ValueError("must be a finite number")
        return value

    @model_validator(mode="before")
    @classmethod
    def _map_legacy_volume(cls, data):
        if isinstance(data, dict) and "auto_trade_volume" in data and "auto_trade_lot_size" not in data:
            data = dict(data)
            data["auto_trade_lot_size"] = data.pop("auto_trade_volume")
        return data

    @model_validator(mode="before")
    @classmethod
    def _sync_strategy_symbols(cls, data):
        if isinstance(data, dict):
            auto = data.get("auto_trade_symbol")
            mt5 = data.get("mt5_symbol")
            if auto and mt5:
                if str(auto).strip().upper() != str(mt5).strip().upper():
                    raise ValueError(
                        "MT5_SYMBOL and AUTO_TRADE_SYMBOL name different "
                        f"instruments ({mt5!r} vs {auto!r}); configure one "
                        "instrument per deployment"
                    )
            elif auto and not mt5:
                data = dict(data)
                data["mt5_symbol"] = str(auto).strip().upper()
            elif mt5 and not auto:
                data = dict(data)
                data["auto_trade_symbol"] = str(mt5).strip().upper()
        return data

    @model_validator(mode="before")
    @classmethod
    def _infer_auto_trade_profile(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        profile_keys = ("auto_trade_profile", "AUTO_TRADE_PROFILE")
        if any(key in data for key in profile_keys):
            return data
        btc_prefixed = any(
            key.lower().startswith("btcusd_") and data.get(key) is not None
            for key in data
        )
        xau_prefixed = any(
            key.lower().startswith("xauusd_") and data.get(key) is not None
            for key in data
        )
        inferred = None
        if btc_prefixed and not xau_prefixed:
            inferred = "BTCUSD"
        elif xau_prefixed and not btc_prefixed:
            inferred = "XAUUSD"
        else:
            for key in ("mt5_symbol", "auto_trade_symbol", "MT5_SYMBOL", "AUTO_TRADE_SYMBOL"):
                value = data.get(key)
                if isinstance(value, str):
                    upper = value.strip().upper()
                    if upper.startswith("BTC"):
                        inferred = "BTCUSD"
                        break
                    if upper.startswith("XAU"):
                        inferred = "XAUUSD"
                        break
        if inferred is None:
            inferred = "XAUUSD"
        data["auto_trade_profile"] = inferred
        return data

    @model_validator(mode="after")
    def validate_application_settings(self) -> "Settings":
        # Reconnect delay validation
        if self.reconnect_max_delay_seconds < self.reconnect_initial_delay_seconds:
            raise ValueError("RECONNECT_MAX_DELAY_SECONDS must be greater than or equal to RECONNECT_INITIAL_DELAY_SECONDS")
        if self.candle_limit > self.max_candle_limit:
            raise ValueError("CANDLE_LIMIT must not exceed MAX_CANDLE_LIMIT")
        if self.allowed_origins == "*":
            if self.app_env == "production":
                raise ValueError("Wildcard origin '*' is not permitted in production. Set ALLOWED_ORIGINS to specific URLs.")
        if self.mt5_password is not None and self.mt5_login is None:
            raise ValueError("MT5_LOGIN is required when MT5_PASSWORD is set")
        if self.mt5_password is not None and self.mt5_server is None:
            raise ValueError("MT5_SERVER is required when MT5_PASSWORD is set")

        if self.auto_trade_symbol is None and self.mt5_symbol:
            self.auto_trade_symbol = self.mt5_symbol

        # Instrument profile resolution
        profile = (self.auto_trade_profile or "").strip().upper()
        if profile not in _PROFILE_DEFAULTS:
            raise ValueError(f"AUTO_TRADE_PROFILE must be one of {sorted(_PROFILE_DEFAULTS)}; received {self.auto_trade_profile!r}")
        prefix = profile.lower()
        defaults = _PROFILE_DEFAULTS[profile]

        instrument = str(getattr(self, f"{prefix}_symbol") or defaults["symbol"])
        provided_symbols = []
        if "mt5_symbol" in self.model_fields_set and self.mt5_symbol:
            provided_symbols.append(("MT5_SYMBOL", str(self.mt5_symbol)))
        if "auto_trade_symbol" in self.model_fields_set and self.auto_trade_symbol:
            provided_symbols.append(("AUTO_TRADE_SYMBOL", str(self.auto_trade_symbol)))
        prefixed_symbol = getattr(self, f"{prefix}_symbol")
        if prefixed_symbol:
            instrument = str(prefixed_symbol)
            for label, value in provided_symbols:
                value_upper = value.upper()
                if value_upper != instrument.upper() and not value_upper.startswith(instrument.upper()):
                    raise ValueError(f"{label}={value!r} conflicts with {profile}_MT5_SYMBOL={prefixed_symbol!r}: different instruments")
        else:
            for label, value in provided_symbols:
                if not value.upper().startswith(profile):
                    raise ValueError(f"{label}={value!r} conflicts with AUTO_TRADE_PROFILE={profile}: different instruments")
            if provided_symbols:
                instrument = provided_symbols[0][1]

        resolved = {"symbol": instrument}

        required_btc = {
            "entry_offset": "AUTO_TRADE_ENTRY_OFFSET",
            "break_even_offset": "AUTO_TRADE_BREAK_EVEN_OFFSET",
            "trailing_distance": "AUTO_TRADE_TRAILING_DISTANCE",
            "lot_size": "AUTO_TRADE_LOT_SIZE",
        }
        missing_required = []

        for name, legacy_field in _LEGACY_PARAM_FIELDS.items():
            prefixed = getattr(self, f"{prefix}_{name}")
            legacy_value = getattr(self, legacy_field)
            legacy_set = legacy_field in self.model_fields_set
            if prefixed is not None:
                if legacy_set and legacy_value is not None and not _same_param(name, legacy_value, prefixed):
                    raise ValueError(
                        f"Conflicting {profile}_{name.upper()}={prefixed!r} and {legacy_field.upper()}={legacy_value!r}: keep only {profile}_{name.upper()}"
                    )
                value = prefixed
            elif legacy_set and legacy_value is not None:
                value = legacy_value
                logger.warning("DEPRECATED: %s now feeds the %s profile; rename it to %s_%s", legacy_field.upper(), profile, profile, name.upper())
            else:
                if profile == "BTCUSD" and name in required_btc:
                    missing_required.append(required_btc[name])
                    continue
                value = defaults[name]

            if name == "symbol_candidates":
                if value is None or str(value).strip() == "":
                    raise ValueError(f"{profile}_MT5_SYMBOL_CANDIDATES must not be empty")
                resolved[name] = str(value).strip()
                continue
            if name == "timeframe":
                if str(value).upper() != "M1":
                    raise ValueError(f"{profile}_{name.upper()}: this static strategy runs on M1 only; received {value!r}")
                resolved[name] = str(value).upper()
                continue
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{profile}_{name.upper()} must be a number; got {value!r}") from exc
            if not math.isfinite(number):
                raise ValueError(f"{profile}_{name.upper()} must be a finite number; got {value!r}")
            if name == "max_entry_deviation_points":
                if int(number) < 0:
                    raise ValueError(f"{profile}_{name.upper()} must not be negative")
                resolved[name] = int(number)
                continue
            if name == "max_spread_points":
                if number < 0:
                    raise ValueError(f"{profile}_{name.upper()} must not be negative; got {value!r}")
                resolved[name] = number
                continue
            if number <= 0:
                raise ValueError(f"{profile}_{name.upper()} must be positive; got {value!r}")
            resolved[name] = number

        if missing_required:
            raise ValueError("BTCUSD profile requires explicitly configured values: " + ", ".join(missing_required))

        if "symbol_candidates" not in resolved:
            resolved["symbol_candidates"] = defaults["symbol_candidates"]

        # Write resolved values
        self.auto_trade_profile = profile
        self.mt5_symbol = str(resolved["symbol"])
        self.auto_trade_symbol = str(resolved["symbol"])
        self.mt5_symbol_candidates = str(resolved["symbol_candidates"])
        self.auto_trade_timeframe = str(resolved["timeframe"])
        self.auto_trade_entry_offset = float(resolved["entry_offset"])
        self.auto_trade_break_even_offset = float(resolved["break_even_offset"])
        self.auto_trade_trailing_distance = float(resolved["trailing_distance"])
        self.auto_trade_lot_size = float(resolved["lot_size"])
        self.auto_trade_max_spread_points = float(resolved["max_spread_points"])
        self.auto_trade_max_entry_deviation_points = int(resolved["max_entry_deviation_points"])

        # BTCUSD must not inherit XAUUSD defaults (already handled by required check)
        instrument = str(self.auto_trade_symbol or self.mt5_symbol or "").upper()
        if instrument.startswith("BTCUSD"):
            required_fields = (
                ("AUTO_TRADE_ENTRY_OFFSET", "auto_trade_entry_offset"),
                ("AUTO_TRADE_BREAK_EVEN_OFFSET", "auto_trade_break_even_offset"),
                ("AUTO_TRADE_TRAILING_DISTANCE", "auto_trade_trailing_distance"),
                ("AUTO_TRADE_LOT_SIZE", "auto_trade_lot_size"),
            )
            missing = [env for env, field in required_fields if field not in self.model_fields_set and getattr(self, field) is None]
            # Already validated above; keep as guard.
            if missing and profile != "BTCUSD":
                raise ValueError("The BTCUSD profile requires explicitly configured values; missing: " + ", ".join(missing))

        if not self.app_read_only:
            raise ValueError("APP_READ_ONLY must remain True for safety")

        return self


# Global settings instance and management functions
_settings_cache: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings_cache
    if _settings_cache is None:
        load_settings()
    return _settings_cache


def load_settings(**overrides) -> Settings:
    global _settings_cache
    try:
        _settings_cache = Settings(**overrides)
    except ValidationError as e:
        guidance_parts = [
            "Invalid application configuration detected.",
            "Please check the following:",
            "  - Ensure .env file is present in the project root directory",
            "  - Validate environment variable names (should be UPPER_SNAKE_CASE)",
            "  - Verify settings types and values (e.g., numeric ranges, boolean flags)",
            "  - Check safety settings are correctly configured (e.g., APP_READ_ONLY=True)",
        ]
        error_messages = []
        for error in e.errors():
            loc = error.get("loc", ())
            field_name = loc[0] if loc else "?"
            error_type = error.get("type", "?")
            detail = error.get("msg", "")
            error_messages.append(f"  - {field_name}: {error_type} ({detail})")
        if "APP_READ_ONLY" in str(e):
            guidance_parts.append("  - APP_READ_ONLY must remain True for safety")
        detailed_error = ConfigurationError(
            "\n".join(guidance_parts) + f"\n\nValidation details:\n" + "\n".join(error_messages)
        )
        detailed_error.__cause__ = e
        raise detailed_error
    return _settings_cache


def reset_settings_cache() -> None:
    global _settings_cache
    _settings_cache = None


PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent

Settings = Settings

__all__ = [
    "PROJECT_ROOT",
    "Settings",
    "ConfigurationError",
    "get_settings",
    "load_settings",
    "reset_settings_cache",
]
