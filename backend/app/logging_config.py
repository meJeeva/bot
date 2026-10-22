"""Structured logging configuration.

Every log record carries a timestamp, level, logger name and message. Two
formats are supported:

* ``console`` - human readable, coloured-free, ideal while developing.
* ``json``    - one JSON object per line, ideal for shipping to a collector.

A redaction filter runs on every record so that credentials can never leak
into the log stream, even if a third-party library tries to log them.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any, Iterable

_CONFIGURED = False

# Keys that must never appear in log output.
_REDACTED = "***REDACTED***"

# key=value / "key": "value" style secrets produced by our own logging.
_SECRET_KEY_PATTERN = re.compile(
    r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|authorization)\b"
    r"(\s*[=:]\s*)(\"?)([^\s\"&,;]+)(\"?)"
)

# Broker credentials in MT5 account dumps (login is masked, never the password).
_MT5_CREDENTIAL_PATTERN = re.compile(
    r"(?i)\b(mt5_password|mt5_login)\b(\s*[=:]\s*)(\"?)([^\s\"&,;]+)(\"?)"
)


class SecretRedactionFilter(logging.Filter):
    """Scrub credential-looking values out of log records."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True

        redacted = _SECRET_KEY_PATTERN.sub(
            lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{_REDACTED}{m.group(5)}",
            message,
        )
        redacted = _MT5_CREDENTIAL_PATTERN.sub(
            lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{_REDACTED}{m.group(5)}",
            redacted,
        )

        if redacted != message:
            record.msg = redacted
            record.args = ()

        return True


class ConsoleFormatter(logging.Formatter):
    """``2026-10-12T05:39:10.123Z | INFO     | app.mt5.connection | message``"""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:  # noqa: N802 - logging API
        """UTC, second precision, ISO-8601. Milliseconds are added separately."""
        return datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            datefmt or "%Y-%m-%dT%H:%M:%S"
        )

    def format(self, record: logging.LogRecord) -> str:
        record.msecs_text = f"{int(record.msecs):03d}"
        return super().format(record)


class JsonFormatter(logging.Formatter):
    """One JSON object per line - structured logs for machines."""

    _RESERVED: Iterable[str] = (
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key in self._RESERVED or key.startswith("_"):
                continue
            if key in ("asctime", "msecs_text"):
                continue
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                value = repr(value)
            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO", log_format: str = "console") -> None:
    """Configure the root logger. Safe to call more than once."""
    global _CONFIGURED

    numeric_level = getattr(logging, str(level).upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(numeric_level)

    # Replace handlers we own so repeated calls do not duplicate output.
    for handler in list(root.handlers):
        if getattr(handler, "_app_handler", False):
            root.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler._app_handler = True  # type: ignore[attr-defined]

    if str(log_format).lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            ConsoleFormatter(
                "%(asctime)s.%(msecs_text)sZ | %(levelname)-8s | %(name)s | %(message)s"
            )
        )

    handler.addFilter(SecretRedactionFilter())
    root.addHandler(handler)

    # uvicorn installs its own handlers; route them through ours.
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(noisy)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True

    # The MT5 handshake is chatty at DEBUG level only; keep it quiet.
    logging.getLogger("MetaTrader5").setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a module logger."""
    return logging.getLogger(name)
