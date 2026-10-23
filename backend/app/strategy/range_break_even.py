"""Pure value/trailing calculations for the XAUUSD M1 strategy.

Every offset in this module is an **absolute price difference of 1.00**, not a
pip, point or broker tick.  Prices are normalised to the symbol's own tick size
only at the edge (when an MT5 request is built); the arithmetic itself is kept
exact so the required one-unit offsets cannot silently change.

Formulas (R is the market reference captured for the cycle):

* Buy entry  = R + 1.00, initial Buy SL  = R
* Sell entry = R - 1.00, initial Sell SL = R
* Buy break-even activation  = Buy entry + 1.00
* Buy trailing stop          = highest favourable price - 1.00
* Sell break-even activation = Sell entry - 1.00
* Sell trailing stop         = lowest favourable price + 1.00

Break-even stops only ever move in the protective direction.  This module
expresses that as ``max`` (buy) and ``min`` (sell), which makes loosening a stop
impossible by construction.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Required absolute XAUUSD price offset.  Do not reinterpret as a pip/point.
PRICE_OFFSET = 1.0

#: The only symbol and chart timeframe this strategy is allowed to trade.
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
    substitutes a different threshold.  With XAUUSD's usual tick size of 0.01
    a calculated 4101.00 stays 4101.00.
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
) -> CycleLevels:
    """Calculate the Phase 1 levels for a new cycle."""
    ref = normalize_price(reference, tick_size, digits)
    if ref is None:
        raise ValueError("A finite market reference value is required")
    buy_entry = normalize_price(ref + PRICE_OFFSET, tick_size, digits)
    sell_entry = normalize_price(ref - PRICE_OFFSET, tick_size, digits)
    initial_buy_sl = normalize_price(ref, tick_size, digits)
    initial_sell_sl = normalize_price(ref, tick_size, digits)
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
def buy_activation_price(entry_price: float) -> float:
    """Market at or above this price activates the buy trailing stop."""
    return float(entry_price) + PRICE_OFFSET


def sell_activation_price(entry_price: float) -> float:
    """Market at or below this price activates the sell trailing stop."""
    return float(entry_price) - PRICE_OFFSET


def buy_break_even_level(highest_favourable_price: float) -> float:
    """Buy protective stop for the highest favourable price seen."""
    return float(highest_favourable_price) - PRICE_OFFSET


def sell_break_even_level(lowest_favourable_price: float) -> float:
    """Sell protective stop for the lowest favourable price seen."""
    return float(lowest_favourable_price) + PRICE_OFFSET


def next_buy_stop_loss(
    previous_stop_loss: float | None,
    highest_favourable_price: float,
) -> float:
    """New buy stop; it can only rise or stay unchanged."""
    candidate = buy_break_even_level(highest_favourable_price)
    if previous_stop_loss is None:
        return candidate
    return max(float(previous_stop_loss), candidate)


def next_sell_stop_loss(
    previous_stop_loss: float | None,
    lowest_favourable_price: float,
) -> float:
    """New sell stop; it can only fall or stay unchanged."""
    candidate = sell_break_even_level(lowest_favourable_price)
    if previous_stop_loss is None:
        return candidate
    return min(float(previous_stop_loss), candidate)


__all__ = [
    "PRICE_OFFSET",
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
]
