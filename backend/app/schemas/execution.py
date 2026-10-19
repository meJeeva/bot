"""Phase 4 execution request and response schemas.

These validate and document every ``/api/execution/*`` payload the same way
the Phase 2/3 schema modules do. Missing values are ``None`` - never zero -
so a missing input can never read as an authorized trade. No schema in this
module accepts arbitrary order parameters: callers can only ever reference a
strategy setup, never prices, volume or an account identity.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class RiskAssessment(BaseModel):
    """Typed, explainable outcome of the risk engine for one candidate trade.

    ``allowed=False`` is authoritative; ``reasons`` is machine-readable and
    exhaustive (every failed check contributes an explicit code).
    """

    model_config = ConfigDict(extra="forbid")

    allowed: bool
    setup_id: str
    symbol: str
    timeframe: str
    direction: Literal["buy", "sell"]
    source: str = "live_strategy"

    # Money values are None when they could not be computed - never 0.
    risk_budget: Optional[float] = Field(
        default=None, description="Most restrictive permitted monetary risk."
    )
    budget_breakdown: dict[str, float] = Field(default_factory=dict)
    estimated_loss: Optional[float] = Field(
        default=None, description="Estimated account-currency loss at the stop."
    )
    proposed_volume: Optional[float] = Field(
        default=None, description="Broker-valid volume rounded DOWN to the step."
    )
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    stop_distance_points: Optional[float] = None
    reward_risk_ratio: Optional[float] = None
    estimated_margin: Optional[float] = None

    account_equity: Optional[float] = None
    account_currency: Optional[str] = None
    quote_age_seconds: Optional[float] = None
    spread_points: Optional[float] = None

    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    config_fingerprint: str = ""
    generated_at: datetime


class ExecutionStatusOut(BaseModel):
    """Authorization + lifecycle posture of the demo execution subsystem."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["disabled", "verifying_account", "demo_verified", "armed", "blocked", "error"]
    configured: bool
    armed: bool
    demo_verified: bool
    account_type: Optional[str] = None
    account_login_masked: Optional[str] = None
    account_server: Optional[str] = None
    account_currency: Optional[str] = None
    reasons: list[str] = Field(default_factory=list)
    last_verified_at: Optional[datetime] = None
    armed_at: Optional[datetime] = None
    last_error: Optional[str] = None

    # Risk posture.
    daily_lockout: Optional[str] = None
    drawdown_lockout: Optional[str] = None
    consecutive_losses: int = 0
    unresolved_executions: int = 0
    last_reconciled_at: Optional[datetime] = None

    # Counters and safety metadata.
    total_executions: int = 0
    open_bot_positions: int = 0
    persistence_available: bool = True
    signal_source: Literal["live_strategy"] = "live_strategy"
    trading_enabled: bool = False
    live_trading_supported: bool = False
    timestamp: datetime


class RiskStatusOut(BaseModel):
    """Current risk limits and their live consumption."""

    model_config = ConfigDict(extra="forbid")

    limits: dict[str, Any]
    risk_date: Optional[str] = None
    baseline_equity: Optional[float] = None
    current_equity: Optional[float] = None
    daily_loss: Optional[float] = None
    daily_loss_limit: Optional[float] = None
    high_water_equity: Optional[float] = None
    drawdown: Optional[float] = None
    drawdown_limit: Optional[float] = None
    aggregate_risk: Optional[float] = None
    aggregate_risk_limit: Optional[float] = None
    open_bot_positions: int = 0
    max_open_positions: int = 0
    bot_positions_missing_stop: int = 0
    external_positions: int = 0
    pending_bot_orders: int = 0
    exposure_unresolved: bool = False
    lockout_reason: Optional[str] = None
    consecutive_losses: int = 0
    timestamp: datetime


class ExecutionRecordOut(BaseModel):
    """One durable execution record (audit + recovery view)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    idempotency_key: str
    setup_id: str
    symbol: str
    timeframe: str
    direction: str
    source: str
    state: str
    stage: Optional[str] = None
    signal_time_utc: Optional[datetime] = None
    confirmation_time_utc: Optional[datetime] = None
    requested_volume: Optional[float] = None
    actual_volume: Optional[float] = None
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    risk_budget: Optional[float] = None
    estimated_loss: Optional[float] = None
    broker_retcode: Optional[int] = None
    broker_order_id: Optional[int] = None
    broker_deal_id: Optional[int] = None
    position_id: Optional[int] = None
    fill_price: Optional[float] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    reconciliation: Optional[str] = None
    account_login_masked: Optional[str] = None
    account_server: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ExecutionHistoryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    unresolved: int
    executions: list[ExecutionRecordOut]


class EnableExecutionIn(BaseModel):
    """Deliberate confirmation token - an accidental POST must not arm."""

    model_config = ConfigDict(extra="forbid")

    confirm: str = Field(
        description='Must be exactly "enable-demo-execution".'
    )


class AssessSetupIn(BaseModel):
    """Request a risk assessment for an existing live strategy setup."""

    model_config = ConfigDict(extra="forbid")

    setup_id: str = Field(min_length=1, max_length=64)


class ReconcileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: str = Field(description='Must be exactly "reconcile".')


class UnlockRiskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: str = Field(
        description='Must be exactly "acknowledge-risk-recovery".'
    )


__all__ = [
    "AssessSetupIn",
    "EnableExecutionIn",
    "ExecutionHistoryOut",
    "ExecutionRecordOut",
    "ExecutionStatusOut",
    "ReconcileIn",
    "RiskAssessment",
    "RiskStatusOut",
    "UnlockRiskIn",
]
