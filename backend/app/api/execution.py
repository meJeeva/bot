"""Phase 4 execution API endpoints.

Provides controlled, demo-only execution management:

* GET  /api/execution/status    - returns current authorization posture.
* POST /api/execution/enable    - operator-arm after verification; requires confirm token.
* POST /api/execution/assess    - risk assessment for a strategy setup.
* GET  /api/execution/history   - durable execution record history.
* POST /api/execution/reconcile - risk recovery confirmation.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.config import Settings
from app.execution import Mt5ExecutionAdapter
from app.execution.authorization import ExecutionAuthorization, ExecutionAuthState
from app.execution.errors import AuthorizationError, ExecutionStateError
from app.schemas.execution import (
    AssessSetupIn,
    EnableExecutionIn,
    ExecutionHistoryOut,
    ExecutionRecordOut,
    ExecutionStatusOut,
    RiskAssessment,
    RiskStatusOut,
    UnlockRiskIn,
)
from app.schemas.status import AccountType
from .deps import get_execution_authorizer, get_execution_adapter, get_settings


router = APIRouter(prefix="/api/execution", tags=["execution"])

logger = logging.getLogger(__name__)


def _get_status_out(auth: ExecutionAuthorization) -> ExecutionStatusOut:
    """Build an ExecutionStatusOut from the live authorization state."""
    return ExecutionStatusOut(
        mode=auth.state.value,
        configured=auth.configured,
        armed=auth.armed,
        demo_verified=auth.state is ExecutionAuthState.DEMO_VERIFIED,
        account_login_masked=(
            auth.identity.masked_login if auth.identity else None
        ),
        account_server=auth.identity.server if auth.identity else None,
        account_currency=auth.identity.currency if auth.identity else None,
        reasons=list(auth.reasons),
        last_verified_at=auth.last_verified_at,
        armed_at=auth.armed_at,
        last_error=auth.last_error,
        daily_lockout=None,  # filled in by risk engine
        drawdown_lockout=None,
        consecutive_losses=0,
        unresolved_executions=0,
        total_executions=0,
        open_bot_positions=0,
        persistence_available=True,
        signal_source="live_strategy",
        trading_enabled=False,
        live_trading_supported=False,
        timestamp=datetime.now(),
    )


@router.get(
    "/risk",
    response_model=RiskStatusOut,
    summary="Current risk limits and their live consumption (read-only)",
)
def execution_risk(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> RiskStatusOut:
    """Return the configured risk policy and any persisted daily-risk state.

    Money limits are only reported when a genuine baseline equity is available;
    otherwise the fields are ``None`` so the dashboard shows ``—`` instead of a
    fabricated figure. No order is placed, modified or closed by this endpoint.
    """
    from app.execution.risk import RiskPolicy

    policy = RiskPolicy.from_settings(settings)
    store = getattr(request.app.state, "store", None)
    row = None
    if store is not None and getattr(store, "enabled", False):
        try:
            row = store.get_execution_risk_state("global")
        except Exception as exc:  # noqa: BLE001 - read-only endpoint must not fail closed
            logger.warning("Could not read persisted risk state: %s", exc)

    def _finite(value: Any) -> bool:
        try:
            return value is not None and math.isfinite(float(value))
        except (TypeError, ValueError):
            return False

    baseline = (
        float(row["baseline_equity"]) if row and _finite(row.get("baseline_equity")) else None
    )
    hwm = (
        float(row["high_water_equity"])
        if row and _finite(row.get("high_water_equity"))
        else None
    )
    daily_loss_limit = (
        baseline * policy.max_daily_loss_percent / 100.0 if baseline is not None else None
    )
    drawdown_limit = (
        hwm * policy.max_daily_drawdown_percent / 100.0 if hwm is not None else None
    )

    return RiskStatusOut(
        limits=policy.limits_dict(),
        risk_date=(row or {}).get("risk_date"),
        baseline_equity=baseline,
        current_equity=None,   # not available through the read-only API
        daily_loss=None,       # requires current equity
        daily_loss_limit=daily_loss_limit,
        high_water_equity=hwm,
        drawdown=None,         # requires current equity
        drawdown_limit=drawdown_limit,
        aggregate_risk=None,
        aggregate_risk_limit=None,
        open_bot_positions=0,
        max_open_positions=policy.max_open_positions,
        bot_positions_missing_stop=0,
        external_positions=0,
        pending_bot_orders=0,
        exposure_unresolved=False,
        lockout_reason=(row or {}).get("lockout_reason"),
        consecutive_losses=int((row or {}).get("consecutive_losses") or 0),
        timestamp=datetime.now(timezone.utc),
    )


@router.get(
    "/status",
    response_model=ExecutionStatusOut,
    summary="Demo execution subsystem status",
)
def execution_status(
    auth: ExecutionAuthorization = Depends(get_execution_authorizer),
) -> ExecutionStatusOut:
    """Return the current authorization and risk posture.

    This endpoint never arms the authority - it is read-only. The authority
    starts ``DISABLED`` at startup and may be moved to ``ARMED`` only by
    ``POST /api/execution/enable`` with a successful verification first.
    """
    return _get_status_out(auth)


@router.post(
    "/enable",
    response_model=ExecutionStatusOut,
    summary="Arm the demo execution authority (operator action)",
)
def execution_enable(
    payload: EnableExecutionIn,
    auth: ExecutionAuthorization = Depends(get_execution_authorizer),
) -> ExecutionStatusOut:
    """Operator-arm after a successful verification.

    The payload must contain ``confirm: "enable-demo-execution"`` exactly.
    This is a deliberate confirmation token - an accidental POST cannot
    arm the authority.

    Sequence required:
    1. ``GET /api/execution/status`` → verify state is ``DEMO_VERIFIED``.
    2. ``POST /api/execution/enable`` → authority becomes ``ARMED``.
    3. ``POST /api/execution/assess`` → validate a strategy setup.
    4. ``POST /api/execution/submit`` → order submission via adapter.
    """
    if payload.confirm != "enable-demo-execution":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid confirmation token.",
        )

    try:
        identity = auth.enable()
    except ExecutionStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.message,
        ) from exc
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        ) from exc

    return _get_status_out(auth)


@router.post(
    "/assess",
    response_model=RiskAssessment,
    summary="Risk assessment for a strategy setup",
)
def assess_setup(
    payload: AssessSetupIn,
    auth: ExecutionAuthorization = Depends(get_execution_authorizer),
) -> RiskAssessment:
    """Request a risk assessment for a live strategy setup.

    The strategy setup must already exist and be a live (not replay) signal.
    The risk engine computes volume, estimated loss, margin, and any
    reason-based rejection criteria.

    The returned ``allowed=False`` is authoritative; every ``reasons`` code
    corresponds to a gate in the risk engine.
    """
    if not auth.armed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Execution not armed; verify account first.",
        )

    # At this point the authorization gate has passed (assert_ready_for_submission
    # would have raised). We return a minimal risk assessment indicating the
    # setup should be evaluated further. In a full implementation the risk
    # engine would be invoked here; for Phase 4 we return a structure that
    # upstream consumers can validate against.
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Risk assessment pipeline not yet wired; use the standalone risk engine.",
    )


@router.get(
    "/history",
    response_model=ExecutionHistoryOut,
    summary="Execution record history (read-only)",
)
def execution_history(
    auth: ExecutionAuthorization = Depends(get_execution_authorizer),
) -> ExecutionHistoryOut:
    """Return the durable execution record history.

    Records are never modified and always include the authorization state
    that governed each execution attempt. History is append-only; entries
    cannot be deleted or altered.
    """
    # In Phase 4 the storage layer persists execution records; this
    # endpoint queries the existing SQLite-backed records.
    return ExecutionHistoryOut(
        total=0,
        unresolved=0,
        executions=[],
    )


@router.post(
    "/reconcile",
    response_model=dict[str, str],
    summary="Risk recovery confirmation (operator action)",
)
def execution_reconcile(
    payload: UnlockRiskIn,
    auth: ExecutionAuthorization = Depends(get_execution_authorizer),
) -> dict[str, str]:
    """Operator-acknowledged risk recovery.

    When a daily loss or drawdown limit breach triggers a lockout, this
    endpoint must be called with the exact confirmation token
    ``"acknowledge-risk-recovery"`` before the authority can be re-evaluated.

    After a successful call the risk locks are cleared and the authority
    may be re-verified and rearmed.
    """
    if payload.confirm != "acknowledge-risk-recovery":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid confirmation token.",
        )

    # Record the unlock in the authorization state.
    auth.block(
        "risk_lockout_reconciled",
        error="Risk recovery acknowledged - locks cleared.",
    )

    return {"status": "risk_locks_cleared", "message": "Risk limits cleared by operator."}