"""Trading strategy building blocks.

The strategy is deliberately pure here: level calculations and the
break-even rules have no MT5, clock or I/O dependencies, so they can be
verified directly against the specification.
"""

from .range_break_even import (
    PRICE_OFFSET,
    STRATEGY_SYMBOL,
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
