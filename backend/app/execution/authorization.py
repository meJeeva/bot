"""Layered demo-execution authorization (Phase 4).

Fail-closed by construction. Orders may only be sent when *every* layer holds:

1. ``EXECUTION_ENABLED`` with a configured demo login and server (capability).
2. A verified account classification from ``account_info().trade_mode`` - the
   MetaTrader account classification itself, never a name heuristic.
3. An exact match against the configured login and broker server.
4. A connected, initialized terminal.
5. An operator action that armed the authority after verification.

The authority object below is what the execution adapter checks immediately
before any order-submission call. It is deliberately independent of the API
layer: a malicious, malformed or incorrect upstream request cannot arm it, and
no stale cached verification survives an account change - any identity change
or verification failure revokes the authority and blocks new submissions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from ..config import Settings
from ..mt5.connection import mask_login
from ..schemas.status import AccountType


class ExecutionAuthState(str, Enum):
    """Authorization states (proposal from the Phase 4 specification)."""

    DISABLED = "disabled"                # not configured / explicitly disarmed
    VERIFYING_ACCOUNT = "verifying_account"
    DEMO_VERIFIED = "demo_verified"       # identity proven, not armed yet
    ARMED = "armed"                       # operator-armed; adapter may submit
    BLOCKED = "blocked"                   # a safety check failed; revocation
    ERROR = "error"                       # verification itself could not run


@dataclass(frozen=True)
class AccountIdentity:
    """The account facts authorization depends on. Never contains secrets."""

    login: int
    server: str
    trade_mode: Optional[int]
    account_type: AccountType
    currency: Optional[str]
    equity: Optional[float]
    balance: Optional[float]
    margin_free: Optional[float]
    leverage: Optional[int] = None

    @property
    def masked_login(self) -> str:
        return mask_login(self.login) or "unknown"


@dataclass(frozen=True)
class VerificationOutcome:
    """Result of one layered verification pass."""

    ok: bool
    reasons: tuple[str, ...]
    identity: Optional[AccountIdentity]

    @property
    def detail(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "reasons": list(self.reasons),
            "account_type": (
                self.identity.account_type.value if self.identity else None
            ),
            "account_login_masked": self.identity.masked_login if self.identity else None,
            "account_server": self.identity.server if self.identity else None,
        }


class DemoAccountVerifier:
    """Evaluates the static demo-identity layers against a live account."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def configured(self) -> bool:
        return self._settings.execution_configured

    @property
    def expected_login(self) -> Optional[int]:
        return self._settings.execution_demo_login

    @property
    def expected_server(self) -> Optional[str]:
        return self._settings.execution_demo_server

    def verify(
        self,
        account: Optional[AccountIdentity],
        *,
        terminal_connected: bool,
        mt5_initialized: bool,
    ) -> VerificationOutcome:
        """Run every static layer. Any failure => not ok (fail closed)."""
        reasons: list[str] = []

        if not self.configured:
            # Not configured is not an error - it is the disabled default.
            return VerificationOutcome(
                ok=False,
                reasons=("execution_not_configured",),
                identity=account,
            )

        if not mt5_initialized:
            reasons.append("mt5_not_initialized")
        if not terminal_connected:
            reasons.append("terminal_disconnected")

        if account is None:
            reasons.append("account_info_unavailable")
            return VerificationOutcome(ok=False, reasons=tuple(reasons), identity=None)

        # The account classification itself - trade_mode 0 is demo, 2 is live,
        # anything else (contest, unknown, unreadable) fails closed.
        if account.account_type is not AccountType.DEMO:
            reasons.append(f"account_not_conclusively_demo:{account.account_type.value}")

        expected_login = self._settings.execution_demo_login
        if expected_login is None:
            reasons.append("execution_demo_login_not_configured")
        elif int(account.login) != int(expected_login):
            # Only masked identity appears anywhere outside configuration.
            reasons.append(
                f"account_login_mismatch:expected_{mask_login(expected_login)}"
                f"_got_{account.masked_login}"
            )

        expected_server = (self._settings.execution_demo_server or "").strip()
        if not expected_server:
            reasons.append("execution_demo_server_not_configured")
        elif account.server.strip().casefold() != expected_server.casefold():
            reasons.append("account_server_mismatch")

        return VerificationOutcome(
            ok=not reasons,
            reasons=tuple(reasons),
            identity=account,
        )


class ExecutionAuthorization:
    """The runtime execution authority consulted by the adapter.

    State transitions:

    * startup            -> ``DISABLED`` (never armed automatically)
    * configured + valid -> ``DEMO_VERIFIED`` (after a successful verification)
    * operator enable    -> ``ARMED`` (only from ``DEMO_VERIFIED``)
    * any failure        -> ``BLOCKED`` (with revocation of a previously armed
      authority; re-arming always requires a fresh successful verification
      *and* a fresh operator enable)
    * identity change    -> ``BLOCKED`` and the previously verified identity is
      discarded; no automatic re-arm path exists.
    """

    def __init__(self, verifier: DemoAccountVerifier) -> None:
        self._verifier = verifier
        self._state = ExecutionAuthState.DISABLED
        self._reasons: tuple[str, ...] = ()
        self._identity: Optional[AccountIdentity] = None
        self._verified_identity: Optional[AccountIdentity] = None
        self._armed_at: Optional[datetime] = None
        self._last_verified_at: Optional[datetime] = None
        self._last_error: Optional[str] = None

    # ------------------------------------------------------------------ read
    @property
    def state(self) -> ExecutionAuthState:
        return self._state

    @property
    def armed(self) -> bool:
        return self._state is ExecutionAuthState.ARMED

    @property
    def configured(self) -> bool:
        return self._verifier.configured

    @property
    def reasons(self) -> tuple[str, ...]:
        return self._reasons

    @property
    def identity(self) -> Optional[AccountIdentity]:
        return self._identity

    @property
    def verified_identity(self) -> Optional[AccountIdentity]:
        return self._verified_identity

    @property
    def armed_at(self) -> Optional[datetime]:
        return self._armed_at

    @property
    def last_verified_at(self) -> Optional[datetime]:
        return self._last_verified_at

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def assert_ready_for_submission(self) -> AccountIdentity:
        """Adapter gate: raises unless the authority is currently ARMED.

        This is the last authorization layer, evaluated again immediately
        before submission regardless of anything the caller checked.
        """
        if self._state is not ExecutionAuthState.ARMED or self._identity is None:
            from .errors import AuthorizationError

            raise AuthorizationError(
                "execution_not_armed",
                "Demo execution is not armed; the order was refused. "
                f"Current state: {self._state.value} "
                f"({', '.join(self._reasons) or 'no reasons recorded'}).",
                detail={"state": self._state.value, "reasons": list(self._reasons)},
            )
        return self._identity

    # ----------------------------------------------------------------- write
    def refresh(
        self,
        account: Optional[AccountIdentity],
        *,
        terminal_connected: bool,
        mt5_initialized: bool,
    ) -> VerificationOutcome:
        """Re-verify the account; revoke the authority on any failure.

        A successful refresh never arms by itself - arming is an explicit
        operator action. A failed refresh always blocks, even if the state was
        previously ``ARMED``.
        """
        now = datetime.now(timezone.utc)
        if not self._verifier.configured:
            self._state = ExecutionAuthState.DISABLED
            self._reasons = ("execution_not_configured",)
            self._identity = account
            return VerificationOutcome(False, self._reasons, account)

        outcome = self._verifier.verify(
            account,
            terminal_connected=terminal_connected,
            mt5_initialized=mt5_initialized,
        )
        self._identity = account

        if not outcome.ok:
            previous = self._state
            # Configured but failing verification is always BLOCKED (only an
            # unconfigured execution stays in the disabled default).
            self._state = ExecutionAuthState.BLOCKED
            self._reasons = outcome.reasons
            if previous is ExecutionAuthState.ARMED:
                # Revocation: the armed authority is gone for good until a
                # fresh verification *and* a fresh operator enable.
                self._armed_at = None
                self._verified_identity = None
            self._last_error = "; ".join(outcome.reasons)
            return outcome

        # Verified identity bookkeeping: a change of account discards the old
        # verification and blocks until re-verified (and re-armed) explicitly.
        if (
            self._verified_identity is not None
            and account is not None
            and (
                int(account.login) != int(self._verified_identity.login)
                or account.server.strip()
                != self._verified_identity.server.strip()
            )
        ):
            self._state = ExecutionAuthState.BLOCKED
            self._reasons = ("account_identity_changed_since_verification",)
            self._verified_identity = None
            self._armed_at = None
            self._last_error = "The account identity changed while armed."
            return VerificationOutcome(False, self._reasons, account)

        self._state = (
            ExecutionAuthState.ARMED
            if self._state is ExecutionAuthState.ARMED
            else ExecutionAuthState.DEMO_VERIFIED
        )
        self._reasons = ()
        self._last_error = None
        self._last_verified_at = now
        if account is not None:
            self._verified_identity = account
        return outcome

    def enable(self) -> AccountIdentity:
        """Operator action: arm a freshly verified demo authority."""
        from .errors import AuthorizationError, ExecutionStateError

        if not self._verifier.configured:
            raise AuthorizationError(
                "execution_not_configured",
                "Demo execution is not configured. Set EXECUTION_ENABLED=true "
                "with EXECUTION_DEMO_LOGIN and EXECUTION_DEMO_SERVER for the "
                "intended demo account.",
            )
        if self._state is ExecutionAuthState.BLOCKED:
            raise ExecutionStateError(
                "Execution is blocked by a safety condition; it cannot be "
                f"enabled until the condition clears: {', '.join(self._reasons)}.",
                detail={"reasons": list(self._reasons)},
            )
        if self._state is not ExecutionAuthState.DEMO_VERIFIED:
            raise ExecutionStateError(
                "Demo execution can only be enabled after a successful demo "
                f"account verification (current state: {self._state.value}).",
                detail={"state": self._state.value, "reasons": list(self._reasons)},
            )
        if self._identity is None:  # pragma: no cover - defensive
            raise AuthorizationError(
                "account_info_unavailable",
                "No verified account identity is available.",
            )
        self._state = ExecutionAuthState.ARMED
        self._armed_at = datetime.now(timezone.utc)
        self._reasons = ()
        return self._identity

    def disable(self) -> None:
        """Immediate disarm. Always succeeds; the safe direction.

        Disabling never *clears* a safety lockout: a BLOCKED authority stays
        blocked (it is simply not armed), so the disarm control cannot be used
        to escape a revocation.
        """
        self._armed_at = None
        if self._state is ExecutionAuthState.BLOCKED:
            return
        self._state = (
            ExecutionAuthState.DEMO_VERIFIED
            if (self._verifier.configured and self._last_verified_at is not None)
            else ExecutionAuthState.DISABLED
        )

    def block(self, *reasons: str, error: str | None = None) -> None:
        """Record a safety lockout (risk limit, unresolved outcome, ...)."""
        self._state = ExecutionAuthState.BLOCKED
        self._reasons = tuple(reasons)
        self._armed_at = None
        self._verified_identity = None
        self._last_error = error or "; ".join(reasons)

    def mark_error(self, message: str) -> None:
        """Verification could not be evaluated at all (fail closed)."""
        if self._state is not ExecutionAuthState.ARMED:
            self._state = ExecutionAuthState.ERROR
        self._last_error = message


__all__ = [
    "AccountIdentity",
    "DemoAccountVerifier",
    "ExecutionAuthState",
    "ExecutionAuthorization",
    "VerificationOutcome",
]
