"""Consistent error handling for the REST API.

Every failure - validation, missing data, MT5 trouble or an unexpected
exception - is rendered as::

    {"error": {"code": "...", "message": "...", "detail": ...}}

so the dashboard never has to guess at a response shape.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logging_config import get_logger

logger = get_logger(__name__)


class ApiError(Exception):
    """An error that should be returned to the client as a JSON envelope."""

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


def error_body(code: str, message: str, detail: Any | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "detail": detail}}


def install_error_handlers(app: FastAPI) -> None:
    """Register the JSON error handlers on ``app``."""

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:  # noqa: ANN202
        return JSONResponse(
            status_code=exc.status_code,
            content=jsonable_encoder(error_body(exc.code, exc.message, exc.detail)),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:  # noqa: ANN202
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder(
                error_body(
                    "validation_error",
                    "The request parameters are invalid.",
                    exc.errors(),
                )
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:  # noqa: ANN202
        return JSONResponse(
            status_code=exc.status_code,
            content=jsonable_encoder(
                error_body(
                    f"http_{exc.status_code}",
                    str(exc.detail) if exc.detail else "Request failed.",
                    None,
                )
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:  # noqa: ANN202
        logger.exception("Unhandled error while serving a request")
        return JSONResponse(
            status_code=500,
            content=jsonable_encoder(
                error_body(
                    "internal_error",
                    "An unexpected internal error occurred. Check the backend log.",
                    None,
                )
            ),
        )
