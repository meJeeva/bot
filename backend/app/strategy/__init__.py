"""Trading strategy building blocks.

Pure, testable strategy logic lives here. No MT5, clock or I/O dependencies
in the calculation helpers; integration with execution happens in services.
"""

from .trend_pullback import *  # noqa: F401,F403

__all__ = []  # populated by submodule via *
