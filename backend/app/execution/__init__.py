"""Phase 4: demo-only execution, risk management and order lifecycle.

This package is the only place in the codebase that may reach MetaTrader order
submission, and only through :class:`~app.execution.adapter.Mt5ExecutionAdapter`
after every fail-closed layer has passed:

* configuration (demo identity, risk policy),
* runtime demo-account verification and an explicit operator arm,
* signal eligibility (live Fibonacci setups only - never replay),
* protective-level and position-sizing validation,
* daily-loss, drawdown and aggregate-exposure limits,
* durable idempotency and reconciliation state.

There is no live-trading mode. The adapter independently re-checks the
authorization before every submission call, so no upstream API, frontend
request or stale cached state can bypass the demo-only restriction.
"""

from .authorization import (
    AccountIdentity,
    DemoAccountVerifier,
    ExecutionAuthState,
    ExecutionAuthorization,
    VerificationOutcome,
)
from .errors import (
    AuthorizationError,
    ExecutionError,
    ExecutionLimitError,
    ExecutionNotFoundError,
    ExecutionStateError,
    ExecutionUnavailableError,
    RiskRejectedError,
)
from .adapter import Mt5ExecutionAdapter

__all__ = [
    "AccountIdentity",
    "AuthorizationError",
    "DemoAccountVerifier",
    "ExecutionAuthState",
    "ExecutionAuthorization",
    "ExecutionError",
    "ExecutionLimitError",
    "ExecutionNotFoundError",
    "ExecutionStateError",
    "ExecutionUnavailableError",
    "Mt5ExecutionAdapter",
    "RiskRejectedError",
    "VerificationOutcome",
]
