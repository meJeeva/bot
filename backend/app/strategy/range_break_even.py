"""Pure value/trailing calculations for the M1 stop-order strategy.

Every offset in this module is an **absolute price difference in the
configured instrument's own price units** (XAUUSD by default, BTCUSD on the
crypto deployment), never a pip, point or broker tick.  Prices are normalised
to the symbol's own tick size only at the edge (when an MT5 request is built);
the arithmetic itself is kept exact so the required offsets cannot silently
change.

The formulas are instrument-independent - with the configured entry offset E,
break-even activation B and trailing distance T, and R the market reference
captured for the cycle:

* Buy entry  = R + E, initial Buy SL  = R
* Sell entry = R - E, initial Sell SL = R
* Buy break-even activation  = Buy entry + B
* Buy trailing stop          = highest favourable price - T
* Sell break-even activation = Sell entry - B
* Sell trailing stop         = lowest favourable price + T

Break-even stops only ever move in the protective direction.  This module
expresses that as ``max`` (buy) and ``min`` (sell), which makes loosening a stop
impossible by construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Required absolute entry offset for the DEFAULT instrument (XAUUSD).  Do
#: not reinterpret as a pip/point.  The controller uses the configured
#: ``AUTO_TRADE_ENTRY_OFFSET`` instead whenever one is set (required for BTCUSD).
PRICE_OFFSET = 1.0

#: Break-even activation offset applied after entry.
BREAK_EVEN_OFFSET = 0.4
BREAK_EVEN_ACTIVATION_OFFSET = BREAK_EVEN_OFFSET
BE_OFFSET = BREAK_EVEN_OFFSET
ACTIVATION_OFFSET = BREAK_EVEN_OFFSET

#: Static follow-up trailing distance applied after break-even activation.
#: This is deliberately separate from PRICE_OFFSET: entry offsets remain 1.00.
TRAILING_DISTANCE = 0.4
TRAIL_OFFSET = TRAILING_DISTANCE
TRAILING_OFFSET = TRAILING_DISTANCE
TRAIL_DISTANCE = TRAILING_DISTANCE
TRAILING_STOP_DISTANCE = TRAILING_DISTANCE
STOP_TRAILING_DISTANCE = TRAILING_DISTANCE
BREAK_EVEN_TRAILING_DISTANCE = TRAILING_DISTANCE
FOLLOW_UP_TRAILING_DISTANCE = TRAILING_DISTANCE
FOLLOW_UP_DISTANCE = TRAILING_DISTANCE
STATIC_TRAILING_DISTANCE = TRAILING_DISTANCE
STATIC_TRAILING_DISTANCE_UNITS = TRAILING_DISTANCE
BE_TRAILING_DISTANCE = TRAILING_DISTANCE

#: Default symbol and chart timeframe.  The controller's configured
#: ``AUTO_TRADE_SYMBOL`` / ``MT5_SYMBOL`` and ``AUTO_TRADE_TIMEFRAME`` take
#: precedence; nothing in the strategy itself is instrument-specific.
STRATEGY_SYMBOL = "XAUUSD"
STRATEGY_TIMEFRAME = "M1"


@dataclass(frozen=True)
class CycleLevels:
    """The four levels calculated from one market reference value."""

    reference: float
    buy_entry: float
    buy_sl: float
    sell_entry: float
    sell_sl: float


def normalize_price(
    price: float | None,
    tick_size: float | None = None,
    digits: int | None = None,
) -> float | None:
    """Return ``price`` normalised to a valid symbol tick.

    The normalisation is a rounding of the already-calculated value; it never
    substitutes a different threshold.  With the usual 0.01 tick size a
    calculated 4101.00 stays 4101.00; a BTCUSD tick of 0.01 or 0.1 normalises
    against the broker's own reported metadata.
    """
    if price is None:
        return None
    value = float(price)
    if tick_size is not None and tick_size > 0:
        steps = round(value / tick_size)
        value = steps * tick_size
    if digits is not None and digits >= 0:
        value = round(value, int(digits))
    return value


def price_tolerance(
    tick_size: float | None = None,
    digits: int | None = None,
) -> float:
    """A comparison tolerance smaller than one tick.

    Broker SLTP levels can come back normalised by the terminal, so equality
    is never tested with ``==``.  The half-tick tolerance absorbs float noise
    without ever accepting a materially loosened stop.
    """
    if tick_size is not None and tick_size > 0:
        return float(tick_size) / 2.0 + 1e-9
    if digits is not None and digits >= 0:
        return 0.5 * (10.0 ** -int(digits)) + 1e-9
    return 1e-6


def build_cycle_levels(
    reference: float,
    tick_size: float | None = None,
    digits: int | None = None,
    entry_offset: float | None = None,
) -> CycleLevels:
    """Calculate the Phase 1 levels for a new cycle.

    ``entry_offset`` is the configured absolute entry distance; the module
    default (``PRICE_OFFSET``) applies only when the caller passes nothing.
    """
    offset = PRICE_OFFSET if entry_offset is None else float(entry_offset)
    ref = normalize_price(reference, tick_size, digits)
    if ref is None:
        raise ValueError("A finite market reference value is required")
    buy_entry = normalize_price(ref + offset, tick_size, digits)
    sell_entry = normalize_price(ref - offset, tick_size, digits)
    # Initial protective stops are derived from each entry's own price, not
    # from the cycle reference, so an entry that differs from the reference
    # by more than the configured offset keeps that difference in its SL.
    initial_buy_sl = normalize_price(
        (buy_entry if buy_entry is not None else ref + offset) - offset,
        tick_size,
        digits,
    )
    initial_sell_sl = normalize_price(
        (sell_entry if sell_entry is not None else ref - offset) + offset,
        tick_size,
        digits,
    )
    assert buy_entry is not None and sell_entry is not None
    assert initial_buy_sl is not None and initial_sell_sl is not None
    return CycleLevels(
        reference=ref,
        buy_entry=buy_entry,
        buy_sl=initial_buy_sl,
        sell_entry=sell_entry,
        sell_sl=initial_sell_sl,
    )


# ----------------------------------------------------------------------
# Break-even boundaries
# ----------------------------------------------------------------------
_ACTIVATION_OFFSET_KEYS = (
    "break_even_offset",
    "activation_offset",
    "be_offset",
    "offset",
    "value",
)
_TRAILING_DISTANCE_KEYS = (
    "trailing_distance",
    "distance",
    "trail_distance",
    "value",
)


def _resolve_value(explicit, kwargs, keys, default):
    if explicit is not None:
        return explicit
    for key in keys:
        if key in kwargs and kwargs[key] is not None:
            return kwargs[key]
    return default


def buy_activation_price(entry_price: float, break_even_offset: float | None = None, **kwargs) -> float:
    """Market at or above this price activates the buy trailing stop."""
    offset = _resolve_value(
        break_even_offset, kwargs, _ACTIVATION_OFFSET_KEYS, BREAK_EVEN_OFFSET
    )
    return float(entry_price) + float(offset)


def sell_activation_price(entry_price: float, break_even_offset: float | None = None, **kwargs) -> float:
    """Market at or below this price activates the sell trailing stop."""
    offset = _resolve_value(
        break_even_offset, kwargs, _ACTIVATION_OFFSET_KEYS, BREAK_EVEN_OFFSET
    )
    return float(entry_price) - float(offset)


def buy_break_even_level(highest_favourable_price: float, trailing_distance: float | None = None, **kwargs) -> float:
    """Buy protective stop for the highest favourable price seen."""
    distance = _resolve_value(
        trailing_distance, kwargs, _TRAILING_DISTANCE_KEYS, TRAILING_DISTANCE
    )
    return float(highest_favourable_price) - float(distance)


def sell_break_even_level(lowest_favourable_price: float, trailing_distance: float | None = None, **kwargs) -> float:
    """Sell protective stop for the lowest favourable price seen."""
    distance = _resolve_value(
        trailing_distance, kwargs, _TRAILING_DISTANCE_KEYS, TRAILING_DISTANCE
    )
    return float(lowest_favourable_price) + float(distance)


def next_buy_stop_loss(
    previous_stop_loss: float | None,
    highest_favourable_price: float,
    trailing_distance: float | None = None,
    **kwargs,
) -> float:
    """New buy stop; it can only rise or stay unchanged."""
    distance = _resolve_value(
        trailing_distance, kwargs, _TRAILING_DISTANCE_KEYS, TRAILING_DISTANCE
    )
    candidate = buy_break_even_level(highest_favourable_price, distance)
    if previous_stop_loss is None:
        return candidate
    return max(float(previous_stop_loss), candidate)


def next_sell_stop_loss(
    previous_stop_loss: float | None,
    lowest_favourable_price: float,
    trailing_distance: float | None = None,
    **kwargs,
) -> float:
    """New sell stop; it can only fall or stay unchanged."""
    distance = _resolve_value(
        trailing_distance, kwargs, _TRAILING_DISTANCE_KEYS, TRAILING_DISTANCE
    )
    candidate = sell_break_even_level(lowest_favourable_price, distance)
    if previous_stop_loss is None:
        return candidate
    return min(float(previous_stop_loss), candidate)


def calculate_atr(rates: Any, period: int = 14) -> float | None:
    """Simple ATR over completed candles.

    ``rates`` is an iterable of mappings/objects exposing ``high``, ``low``
    and ``close``. The last candle is assumed to be the forming one and is
    excluded, so only completed candles contribute.
    """
    try:
        items = list(rates)
    except Exception:  # noqa: BLE001 - defensive
        return None
    if len(items) < period + 1:
        return None

    def _get(item, name):
        if isinstance(item, dict):
            return item.get(name)
        return getattr(item, name, None)

    completed = items[:-1]
    if len(completed) < period + 1:
        return None
    true_ranges: list[float] = []
    for i in range(1, len(completed)):
        high = float(_get(completed[i], "high"))
        low = float(_get(completed[i], "low"))
        prev_close = float(_get(completed[i - 1], "close"))
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)
    if len(true_ranges) < period:
        return None
    return sum(true_ranges[-period:]) / float(period)


def initial_buy_stop_loss(
    entry_price: float,
    stop_distance: float = 1.0,
    tick_size: float | None = None,
    digits: int | None = None,
) -> float | None:
    """Initial protective stop for a BUY entry.

    The stop is derived from the entry's own price, preserving any difference
    between the entry and the cycle reference.
    """
    return normalize_price(float(entry_price) - float(stop_distance), tick_size, digits)


def initial_sell_stop_loss(
    entry_price: float,
    stop_distance: float = 1.0,
    tick_size: float | None = None,
    digits: int | None = None,
) -> float | None:
    """Initial protective stop for a SELL entry."""
    return normalize_price(float(entry_price) + float(stop_distance), tick_size, digits)


def effective_trailing_distance(
    atr: float | None, multiplier: float, cap: float
) -> float:
    """ATR-based trailing distance, capped by the configured maximum."""
    if atr is None or atr <= 0:
        return float(cap)
    raw = float(atr) * float(multiplier)
    return min(raw, float(cap))


__all__ = [
    "PRICE_OFFSET",
    "BREAK_EVEN_OFFSET",
    "BREAK_EVEN_ACTIVATION_OFFSET",
    "BE_OFFSET",
    "ACTIVATION_OFFSET",
    "TRAILING_DISTANCE",
    "TRAIL_OFFSET",
    "TRAILING_OFFSET",
    "TRAIL_DISTANCE",
    "TRAILING_STOP_DISTANCE",
    "STOP_TRAILING_DISTANCE",
    "BREAK_EVEN_TRAILING_DISTANCE",
    "FOLLOW_UP_TRAILING_DISTANCE",
    "FOLLOW_UP_DISTANCE",
    "STATIC_TRAILING_DISTANCE",
    "STATIC_TRAILING_DISTANCE_UNITS",
    "BE_TRAILING_DISTANCE",
    "STRATEGY_SYMBOL",
    "STRATEGY_TIMEFRAME",
    "CycleLevels",
    "build_cycle_levels",
    "buy_activation_price",
    "buy_break_even_level",
    "next_buy_stop_loss",
    "next_sell_stop_loss",
    "normalize_price",
    "price_tolerance",
    "sell_activation_price",
    "sell_break_even_level",
    "calculate_atr",
    "effective_trailing_distance",
    "initial_buy_stop_loss",
    "initial_sell_stop_loss",
]
