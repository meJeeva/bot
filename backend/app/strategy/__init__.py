"""Trading strategy building blocks.

The strategy is deliberately pure here: level calculations and the
break-even rules have no MT5, clock or I/O dependencies, so they can be
verified directly against the specification.
"""

from .range_break_even import (
    PRICE_OFFSET,
    BREAK_EVEN_OFFSET,
    BREAK_EVEN_ACTIVATION_OFFSET,
    BE_OFFSET,
    ACTIVATION_OFFSET,
    TRAILING_DISTANCE,
    TRAIL_OFFSET,
    TRAILING_OFFSET,
    TRAIL_DISTANCE,
    TRAILING_STOP_DISTANCE,
    STOP_TRAILING_DISTANCE,
    BREAK_EVEN_TRAILING_DISTANCE,
    FOLLOW_UP_TRAILING_DISTANCE,
    FOLLOW_UP_DISTANCE,
    STATIC_TRAILING_DISTANCE,
    STATIC_TRAILING_DISTANCE_UNITS,
    BE_TRAILING_DISTANCE,    STRATEGY_SYMBOL,
    STRATEGY_TIMEFRAME,
    CycleLevels,
    build_cycle_levels,
    buy_activation_price,
    buy_break_even_level,
    next_buy_stop_loss,
    next_sell_stop_loss,
    normalize_price,
    price_tolerance,
    sell_activation_price,
    sell_break_even_level,
)

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
