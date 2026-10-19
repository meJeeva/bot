"""Central timeframe mapping - the single source of truth for Phase 1.

Exactly seven timeframes are supported:

===========  ==================  ===========  ==========================
Name         MT5 constant        Seconds      Meaning
===========  ==================  ===========  ==========================
``M1``        TIMEFRAME_M1            60       One minute
``M5``        TIMEFRAME_M5           300       Five minutes
``M15``       TIMEFRAME_M15          900       Fifteen minutes
``M30``       TIMEFRAME_M30         1800       Thirty minutes
``H1``        TIMEFRAME_H1          3600       One hour
``H4``        TIMEFRAME_H4         14400       Four hours
``D1``        TIMEFRAME_D1         86400       One day
===========  ==================  ===========  ==========================

The ``mt5_value`` fields are read from the installed MetaTrader5 package so
the numbers always match the terminal build in use. If the package is not
importable the documented values from the MetaQuotes API reference are used as
a fallback and a warning is emitted; :class:`~app.mt5.connection.MT5Connection`
still fails fast with an actionable message.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ..logging_config import get_logger

logger = get_logger(__name__)

try:  # pragma: no cover - environment dependent
    import MetaTrader5 as _mt5

    _MT5_AVAILABLE = True
except Exception:  # pragma: no cover - environment dependent
    _mt5 = None  # type: ignore[assignment]
    _MT5_AVAILABLE = False
    logger.warning(
        "MetaTrader5 package is not importable; using documented timeframe "
        "constants. Install backend/requirements.txt to enable terminal access."
    )

# Documented MetaQuotes constants, used only when the package is unavailable.
_FALLBACK_CONSTANTS: Final[dict[str, int]] = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 16385,
    "H4": 16388,
    "D1": 16408,
}

_MT5_ATTRIBUTES: Final[dict[str, str]] = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}

# Preserve the order used across the API and the dashboard.
TIMEFRAME_ORDER: Final[tuple[str, ...]] = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")

_LABELS: Final[dict[str, str]] = {
    "M1": "1 minute",
    "M5": "5 minutes",
    "M15": "15 minutes",
    "M30": "30 minutes",
    "H1": "1 hour",
    "H4": "4 hours",
    "D1": "1 day",
}

_SECONDS: Final[dict[str, int]] = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}


class UnsupportedTimeframeError(ValueError):
    """Raised when an unsupported timeframe name is requested."""

    def __init__(self, value: object) -> None:
        self.value = value
        supported = ", ".join(TIMEFRAME_ORDER)
        super().__init__(
            f"Unsupported timeframe {value!r}. Supported timeframes: {supported}."
        )


@dataclass(frozen=True)
class TimeframeSpec:
    """Description of one supported timeframe."""

    name: str
    mt5_value: int
    seconds: int
    label: str

    @property
    def duration_seconds(self) -> int:
        return self.seconds


def _resolve_constant(name: str) -> int:
    if _MT5_AVAILABLE and _mt5 is not None:
        attribute = _MT5_ATTRIBUTES[name]
        value = getattr(_mt5, attribute, None)
        if isinstance(value, int):
            return value
    return _FALLBACK_CONSTANTS[name]


TIMEFRAMES: Final[dict[str, TimeframeSpec]] = {
    name: TimeframeSpec(
        name=name,
        mt5_value=_resolve_constant(name),
        seconds=_SECONDS[name],
        label=_LABELS[name],
    )
    for name in TIMEFRAME_ORDER
}

SUPPORTED_TIMEFRAMES: Final[tuple[str, ...]] = TIMEFRAME_ORDER

# Reverse lookup: MT5 integer constant -> canonical name.
MT5_VALUE_TO_NAME: Final[dict[int, str]] = {
    spec.mt5_value: spec.name for spec in TIMEFRAMES.values()
}


def normalize_timeframe(value: str) -> str:
    """Normalize and validate a timeframe name.

    Accepts only the seven supported names, case-insensitively.
    Raises :class:`UnsupportedTimeframeError` otherwise.
    """
    if not isinstance(value, str):
        raise UnsupportedTimeframeError(value)

    candidate = value.strip().upper().replace("TIMEFRAME_", "")
    if candidate in TIMEFRAMES:
        return candidate
    raise UnsupportedTimeframeError(value)


def is_supported_timeframe(value: object) -> bool:
    """True when ``value`` names a supported timeframe."""
    if not isinstance(value, str):
        return False
    return value.strip().upper().replace("TIMEFRAME_", "") in TIMEFRAMES


def get_timeframe(value: str) -> TimeframeSpec:
    """Return the :class:`TimeframeSpec` for ``value`` or raise."""
    return TIMEFRAMES[normalize_timeframe(value)]


def get_mt5_timeframe(value: str) -> int:
    """Return the MetaTrader5 integer constant for ``value``."""
    return get_timeframe(value).mt5_value


def timeframe_seconds(value: str) -> int:
    """Return the length of one bar of ``value`` in seconds."""
    return get_timeframe(value).seconds


def name_for_mt5_value(mt5_value: int) -> str | None:
    """Map an MT5 integer constant back to its canonical name."""
    return MT5_VALUE_TO_NAME.get(int(mt5_value))
