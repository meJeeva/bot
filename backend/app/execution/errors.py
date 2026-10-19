"""Phase 4 execution errors.

Execution failures are explicit, code-carrying exceptions so the API can render
them through the project's standard error envelope and the frontend can react
to machine-readable rejection codes. Every safety rejection funnels through
this hierarchy - no check fails silently.
"""

from __future__ import annotations

from typing import Any


class ExecutionError(Exception):
    """Base for every recoverable execution failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        detail: Any | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail
        super().__init__(message)


class AuthorizationError(ExecutionError):
    """The execution authority is missing, revoked or not demo-verified."""

    def __init__(self, code: str, message: str, *, detail: Any | None = None) -> None:
        super().__init__(code, message, status_code=403, detail=detail)


class RiskRejectedError(ExecutionError):
    """A risk check or protective-level validation refused the trade."""

    def __init__(
        self, code: str, message: str, *, detail: Any | None = None
    ) -> None:
        super().__init__(code, message, status_code=422, detail=detail)


class ExecutionNotFoundError(ExecutionError):
    """Unknown execution record or setup id."""

    def __init__(self, ident: str) -> None:
        super().__init__(
            "execution_not_found",
            f"Execution {ident!r} was not found. It may have expired or never existed.",
            status_code=404,
        )


class ExecutionStateError(ExecutionError):
    """The requested operation is not valid in the current lifecycle state."""

    def __init__(self, message: str, *, detail: Any | None = None) -> None:
        super().__init__(
            "execution_invalid_state", message, status_code=409, detail=detail
        )


class ExecutionLimitError(ExecutionError):
    """A resource limit (sessions, requests, exposure) has been reached."""

    def __init__(self, code: str, message: str, *, detail: Any | None = None) -> None:
        super().__init__(code, message, status_code=429, detail=detail)


class ExecutionUnavailableError(ExecutionError):
    """Persistence or the execution subsystem is not available (fail closed)."""

    def __init__(self, code: str, message: str, *, detail: Any | None = None) -> None:
        super().__init__(code, message, status_code=503, detail=detail)


__all__ = [
    "ExecutionError",
    "AuthorizationError",
    "RiskRejectedError",
    "ExecutionNotFoundError",
    "ExecutionStateError",
    "ExecutionLimitError",
    "ExecutionUnavailableError",
]
