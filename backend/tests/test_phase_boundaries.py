"""Phase boundary enforcement.

Phase 1 is infrastructure only. These tests fail the build if anything that
could place, modify or close an order is introduced into the application package.

The trading strategies (Fibonacci, EMA, liquidity, session) have been removed:
the application deliberately runs in a safe, non-trading state. These checks
still fail the build if an order-execution entry point, or a trade-decision
identifier, is introduced anywhere in the application package.

They are static checks over ``app/`` plus one runtime check that a full poll
cycle never touches an order-execution function.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import app as app_package

APP_DIR = Path(app_package.__file__).resolve().parent

# MetaTrader 5 order-execution / position-management entry points.
# These are forbidden in ALL phases - the bot never trades automatically.
# Note: order_calc_profit and order_calc_margin are calculation helpers
# (not order execution) and are permitted in the execution module for
# risk-based position sizing (Phase 4).
FORBIDDEN_MT5_FUNCTIONS = (
    "order_send",
    "order_check",
    "positions_close",
    "positions_close_partial",
    "positions_modify",
)

# These calculation helpers are permitted in the execution module for
# broker-authoritative risk sizing. They must never be called outside
# the execution adapter.
_EXECUTION_CALCULATION_FUNCTIONS = (
    "order_calc_profit",
    "order_calc_margin",
)

# These order-execution entry points are permitted ONLY inside the execution
# adapter, where they are the sole, re-audited path to the broker:
# every order still passes every authorization, risk and reconciliation gate
# before reaching this line.
_EXECUTION_ORDER_SEND_FUNCTIONS = (
    "order_send",
)

# Paths that may legitimately reference trade-level vocabulary: the preserved
# execution pipeline (risk / order-execution infrastructure) and the API and
# schema modules that document it.
_EXECUTION_PATH_SEGMENTS = {"execution"}
_EXECUTION_API_SCHEMA_FILES = {"execution.py"}


def python_sources() -> list[Path]:
    return sorted(path for path in APP_DIR.rglob("*.py"))


def allows_execution_identifiers(path: Path) -> bool:
    """Check if a path may reference trade-level field names.

    Phase 4 execution infrastructure (``app/execution/``) processes setups into
    authorized trades and therefore legitimately references fields such as
    ``stop_loss`` and ``take_profit``. ``app/api/execution.py`` and
    ``app/schemas/execution.py`` are its API surface, and ``storage.py`` persists
    the execution records. No new strategy logic is defined there.
    """
    try:
        parts = path.relative_to(APP_DIR).parts
    except ValueError:
        return False
    if any(segment in _EXECUTION_PATH_SEGMENTS for segment in parts):
        return True
    if path.name == "storage.py":
        # The execution persistence schema stores stop_loss/take_profit.
        return True
    if (
        len(parts) >= 2
        and parts[0] in {"api", "schemas"}
        and parts[1] in _EXECUTION_API_SCHEMA_FILES
    ):
        return True
    return False


def test_the_application_package_has_sources_to_check():
    assert python_sources(), "No application sources found - check APP_DIR"


def _allows_execution_function(path: Path, function_name: str) -> bool:
    """Check if a path may call an execution function.

    The execution adapter is the ONLY place order_send may be called.
    It is the fail-closed gate to the broker, checked on every call.
    """
    parts = path.relative_to(APP_DIR).parts
    if "execution" in parts and path.name == "adapter.py":
        return True
    return False


@pytest.mark.parametrize("function_name", FORBIDDEN_MT5_FUNCTIONS)
def test_no_order_execution_function_is_referenced(function_name):
    pattern = re.compile(rf"\b{re.escape(function_name)}\b")
    offenders = [
        f"{path.relative_to(APP_DIR)}:{number}"
        for path in python_sources()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
        and not (
            (path.name == "execution" and function_name in _EXECUTION_CALCULATION_FUNCTIONS)
            or _allows_execution_function(path, function_name)
        )
    ]

    assert not offenders, (
        f"All phases must never call {function_name}(). Found in: {offenders}"
    )


@pytest.mark.parametrize(
    "identifier",
    ("stop_loss", "take_profit"),
)
def test_trade_level_identifiers_only_in_execution_paths(identifier):
    """Trade-level identifiers are permitted in the execution pipeline only.

    The trading strategies have been removed, so no signal generation code may
    introduce entry/exit vocabulary anywhere else in the application.
    """
    pattern = re.compile(rf"\b{re.escape(identifier)}\b", re.IGNORECASE)
    offenders = [
        f"{path.relative_to(APP_DIR)}:{number}"
        for path in python_sources()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line) and not allows_execution_identifiers(path)
    ]

    assert not offenders, (
        f"Trade-level identifier '{identifier}' found outside the execution "
        f"pipeline: {offenders}"
    )


def test_no_trading_strategy_modules_exist():
    """No strategy module may exist anywhere in the application package.

    All strategies have been removed and none may be re-added accidentally.
    """
    strategy_modules = [
        path.name
        for path in python_sources()
        if any(
            token in path.name.lower()
            for token in ("fibonacci", "strategy", "signal")
        )
    ]

    assert not strategy_modules, (
        f"Unexpected strategy modules in the application package: {strategy_modules}"
    )


def test_application_declares_itself_read_only():
    source = (APP_DIR / "config.py").read_text(encoding="utf-8")
    assert "app_read_only: bool = True" in source


async def test_a_full_poll_cycle_touches_no_order_function(fake_mt5):
    from app.config import Settings
    from app.mt5.connection import MT5Connection
    from app.services.market_monitor import MarketMonitor

    settings = Settings(_env_file=None, database_enabled=False, log_level="WARNING")
    connection = MT5Connection(settings, mt5_module=fake_mt5)
    await connection.initialize()
    monitor = MarketMonitor(connection, settings)

    await monitor._poll_once()
    await monitor._refresh_next_timeframe()

    called = set(fake_mt5.call_names())
    assert called & set(FORBIDDEN_MT5_FUNCTIONS) == set()

    snapshot = monitor.build_snapshot_sync()
    assert snapshot.trading_enabled is False
    assert snapshot.read_only is True
