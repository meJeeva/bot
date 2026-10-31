"""Deterministic harness for the automatic-trading scheduler tests.

A virtual monotonic clock plus a fake market monitor drive the real scheduler
loop without any wall-clock waiting. Every terminal interaction still goes
through the mocked MT5 adapter in ``tests.fakes``; no real order is placed.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Callable

from app.config import Settings
from app.mt5.connection import MT5Connection
from app.services.auto_trading import AutoTradingController


class VirtualClock:
    """A monotonic clock the test advances explicitly."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.value = start

    def now(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += max(0.0, seconds)


class FakeMonitor:
    """Only the surface :class:`AutoTradingController` reads."""

    def __init__(self, symbol: str = "XAUUSD", spread_points: float = 56.0) -> None:
        self.symbol_status = SimpleNamespace(
            requested=symbol, resolved=symbol, resolution="resolved"
        )
        self.quote = SimpleNamespace(
            bid=4185.58, ask=4186.14, spread_points=spread_points, is_stale=False
        )

    def latest_quote(self):
        return self.quote


@dataclass
class OrderEvent:
    """One order_send call, timestamped on the virtual clock."""

    at: float
    request: dict[str, Any]
    open_tickets: list[int] = field(default_factory=list)

    @property
    def is_entry(self) -> bool:
        return "position" not in self.request

    @property
    def is_exit(self) -> bool:
        return "position" in self.request


def install_virtual_time(monkeypatch, clock: VirtualClock) -> None:
    """Make every scheduler wait a zero-cost virtual clock advance."""
    monkeypatch.setattr(AutoTradingController, "_now", lambda self: clock.now())

    async def _sleep(self, seconds: float) -> None:
        clock.advance(seconds)
        await asyncio.sleep(0)

    monkeypatch.setattr(AutoTradingController, "_sleep", _sleep)


async def build_controller(fake_mt5, **overrides):
    """A controller wired to the fake terminal and a live-looking monitor."""
    overrides.setdefault("database_enabled", False)
    overrides.setdefault("log_level", "WARNING")
    overrides.setdefault("auto_trade_demo_authorized", True)
    overrides.setdefault("live_trading_enabled", False)
    settings = Settings(_env_file=None, **overrides)
    connection = MT5Connection(settings, mt5_module=fake_mt5)
    await connection.initialize()
    controller = AutoTradingController(settings, connection, FakeMonitor())
    return controller, connection, settings


def instrument_orders(
    fake_mt5,
    clock: VirtualClock,
    events: list[OrderEvent],
    magic: int,
    *,
    entry_returns_none: bool = False,
):
    """Record every order with its virtual time and the positions open then."""
    original = fake_mt5.order_send

    def order_send(request):
        req = request if isinstance(request, dict) else dict(request)
        events.append(
            OrderEvent(
                at=clock.now(),
                request=req,
                open_tickets=[p.ticket for p in fake_mt5.positions if p.magic == magic],
            )
        )
        result = original(request)
        if entry_returns_none and "position" not in req:
            # Model an ambiguous submission: MT5 executed the order but the
            # client never received a result.
            return None
        return result

    fake_mt5.order_send = order_send
    return original


async def wait_for(predicate: Callable[[], bool], timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not met in time")


async def wait_for_status(controller, expected, timeout: float = 10.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if controller._status in expected:
            return controller._status
        await asyncio.sleep(0.01)
    raise AssertionError(
        f"status stuck at {controller._status!r}; expected one of {expected}"
    )


def entries(events: list[OrderEvent]) -> list[OrderEvent]:
    return [event for event in events if event.is_entry]


def exits(events: list[OrderEvent]) -> list[OrderEvent]:
    return [event for event in events if event.is_exit]
