"""Read-only boundary enforcement.

The trading strategies, backtesting system, shadow system and order-execution
pipeline have been removed. The application now only reads market data from
MetaTrader 5.

These tests fail the build if anything that could place, modify or close an
order is introduced into the application package, or if trade-level vocabulary
reappears outside a market-data contract.

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
FORBIDDEN_MT5_FUNCTIONS = (
    "order_send",
    "order_check",
    "positions_close",
    "positions_close_partial",
    "positions_modify",
    "order_calc_profit",
    "order_calc_margin",
)

# Trade-level vocabulary. The market-data schemas describe bids, asks and
# candles only, so none of these may appear anywhere in the package.
FORBIDDEN_IDENTIFIERS = (
    "stop_loss",
    "take_profit",
    "position_ticket",
    "trade_action",
)


def python_sources() -> list[Path]:
    return sorted(path for path in APP_DIR.rglob("*.py"))


def test_the_application_package_has_sources_to_check():
    assert python_sources(), "No application sources found - check APP_DIR"


@pytest.mark.parametrize("function_name", FORBIDDEN_MT5_FUNCTIONS)
def test_no_order_execution_function_is_referenced(function_name):
    pattern = re.compile(rf"\b{re.escape(function_name)}\b")
    offenders = [
        f"{path.relative_to(APP_DIR)}:{number}"
        for path in python_sources()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]

    assert not offenders, (
        f"The read-only build must never call {function_name}(). Found in: {offenders}"
    )


@pytest.mark.parametrize("identifier", FORBIDDEN_IDENTIFIERS)
def test_no_trade_level_identifier_is_referenced(identifier):
    pattern = re.compile(rf"\b{re.escape(identifier)}\b", re.IGNORECASE)
    offenders = [
        f"{path.relative_to(APP_DIR)}:{number}"
        for path in python_sources()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]

    assert not offenders, (
        f"Trade-level identifier '{identifier}' found outside a market-data "
        f"contract: {offenders}"
    )


def test_no_trading_strategy_modules_exist():
    """No strategy, strategy-adjacent or execution module may exist."""
    forbidden_modules = [
        path.name
        for path in python_sources()
        if any(
            token in path.name.lower()
            for token in ("fibonacci", "strategy", "signal", "backtest", "shadow", "execution")
        )
    ]

    assert not forbidden_modules, (
        f"Unexpected strategy or execution modules in the application package: "
        f"{forbidden_modules}"
    )


def test_no_strategy_or_execution_directories_exist():
    forbidden_dirs = [
        str(path.relative_to(APP_DIR))
        for path in APP_DIR.rglob("*")
        if path.is_dir()
        and any(
            token in path.name.lower()
            for token in ("strategy", "backtest", "shadow", "execution", "research")
        )
    ]

    assert not forbidden_dirs, f"Unexpected strategy/execution directories: {forbidden_dirs}"


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
