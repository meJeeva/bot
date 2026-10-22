"""Stop policies, session cycle limits, and honest closure reporting.

The 5-second / 3-second schedule is unchanged here; these tests only cover how
a session ends. Everything runs on the virtual clock against the fake terminal.
"""

from __future__ import annotations

import asyncio

import pytest

from app.config import Settings
from tests.auto_trading_harness import (
    OrderEvent,
    VirtualClock,
    build_controller,
    entries,
    exits,
    install_virtual_time,
    instrument_orders,
    wait_for,
    wait_for_status,
)
from tests.fakes import FakeOrderResult, FakePosition, gold_terminal_with_live_tick


MAGIC = 9001


def reject_all_closes(fake) -> None:
    """Every close request is refused; entries still work normally."""
    original = fake.order_send

    def order_send(request):
        req = request if isinstance(request, dict) else dict(request)
        if "position" in req:
            return FakeOrderResult(retcode=10013, comment="close rejected")
        return original(request)

    fake.order_send = order_send


def accept_but_keep_position(fake) -> None:
    """The broker accepts the close but MT5 still lists the position."""
    original = fake.order_send

    def order_send(request):
        req = request if isinstance(request, dict) else dict(request)
        if "position" not in req:
            return original(request)
        still_open = [p for p in fake.positions if p.ticket == req["position"]]
        result = original(request)
        fake.positions.extend(still_open)
        return result

    fake.order_send = order_send


# ----------------------------------------------------------------------
# Stop policy: close
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stop_close_policy_flattens_the_position(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_max_cycles=1000, auto_trade_stop_policy="close"
    )
    events: list[OrderEvent] = []
    instrument_orders(fake, clock, events, MAGIC)

    await controller.start()
    await wait_for(lambda: len(entries(events)) >= 1)

    status = await controller.stop()

    assert status.status == "STOPPED"
    assert status.position_status == "none"
    assert status.position_ticket is None
    assert fake.positions == []

    count = len(entries(events))
    await asyncio.sleep(0.05)
    assert len(entries(events)) == count, "Stop did not prevent further entries"


@pytest.mark.asyncio
async def test_stop_never_closes_a_position_it_does_not_own(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    fake.positions.append(
        FakePosition(
            ticket=4242,
            symbol="XAUUSD",
            magic=1234,  # a manual trade, not this strategy
            volume=0.01,
            price_open=4100.0,
        )
    )
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_max_cycles=1000, auto_trade_stop_policy="close"
    )
    events: list[OrderEvent] = []
    instrument_orders(fake, clock, events, MAGIC)

    await controller.start()
    await wait_for(lambda: len(entries(events)) >= 1)

    status = await controller.stop()

    assert status.status == "STOPPED"
    assert status.position_status == "none"
    # Only the strategy ticket was closed; the manual trade is untouched.
    assert [p.ticket for p in fake.positions] == [4242]


@pytest.mark.asyncio
async def test_stop_close_policy_reports_error_when_closure_is_not_confirmed(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_max_cycles=1000, auto_trade_stop_policy="close"
    )
    reject_all_closes(fake)
    events: list[OrderEvent] = []
    instrument_orders(fake, clock, events, MAGIC)

    await controller.start()
    await wait_for(lambda: len(exits(events)) >= 1)

    status = await controller.stop()

    # The Stop asked for a flat book and MT5 never confirmed one.
    assert status.status == "ERROR"
    assert "still open" in (status.last_error or "")
    assert status.position_status == "open"
    assert status.position_ticket is not None
    assert controller._completed_cycles == 0
    assert "exit filled" not in (status.last_exit_result or "")
    assert all(item.status != "closed" for item in controller._history)


# ----------------------------------------------------------------------
# Stop policy: leave
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stop_leave_policy_keeps_the_position_open(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_max_cycles=1000, auto_trade_stop_policy="leave"
    )
    reject_all_closes(fake)  # guarantee a position is open when Stop arrives
    events: list[OrderEvent] = []
    instrument_orders(fake, clock, events, MAGIC)

    await controller.start()
    await wait_for(lambda: len(exits(events)) >= 1)

    status = await controller.stop()

    # Deliberately left open, and reported as such - never as flat.
    assert status.status == "STOPPED"
    assert status.position_status == "open"
    assert status.position_ticket is not None
    assert [p.ticket for p in fake.positions] == [status.position_ticket]
    assert "leave" in (status.last_exit_result or "")
    assert controller._completed_cycles == 0

    # The open position blocked every further entry, and Stop ended the loop.
    assert len(entries(events)) == 1
    assert all(event.open_tickets == [] for event in entries(events))
    count = len(entries(events))
    await asyncio.sleep(0.05)
    assert len(entries(events)) == count


# ----------------------------------------------------------------------
# A submitted close is not a confirmed close
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_accepted_close_is_not_counted_until_mt5_confirms_it(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_max_cycles=1000
    )
    accept_but_keep_position(fake)
    events: list[OrderEvent] = []
    instrument_orders(fake, clock, events, MAGIC)

    await controller.start()
    await wait_for(lambda: len(exits(events)) >= 1)
    # Give the confirmation window time to expire at least once.
    await wait_for(lambda: controller._failed_exits >= 1)

    assert controller._completed_cycles == 0
    assert controller._session_completed_cycles == 0
    assert controller._position_ticket is not None
    assert all(item.status != "closed" for item in controller._history)

    status = await controller.stop()

    assert status.status == "ERROR"
    assert status.position_status == "open"
    assert status.position_ticket is not None


# ----------------------------------------------------------------------
# Session cycle limit
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_max_cycles_is_per_session_and_a_new_session_runs_again(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_max_cycles=1
    )
    events: list[OrderEvent] = []
    instrument_orders(fake, clock, events, MAGIC)

    # --- first session: one cycle, then the limit stops the session ---
    await controller.start()
    await wait_for(lambda: controller._completed_cycles == 1)
    await wait_for_status(controller, {"STOPPED"})

    assert controller._session_completed_cycles == 1
    assert len(entries(events)) == 1
    assert fake.positions == []

    # --- second session: the previous session's count must not block it ---
    await controller.start()
    await wait_for(lambda: controller._completed_cycles == 2)
    await wait_for_status(controller, {"STOPPED"})

    assert controller._session_completed_cycles == 1, "limit must be per session"
    assert controller._completed_cycles == 2, "lifetime statistic is preserved"
    assert len(entries(events)) == 2
    assert fake.positions == []
    assert controller._status == "STOPPED"


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
def test_stop_policy_defaults_and_validation():
    assert Settings(_env_file=None, database_enabled=False).auto_trade_stop_policy == "close"
    assert (
        Settings(
            _env_file=None, database_enabled=False, auto_trade_stop_policy="leave"
        ).auto_trade_stop_policy
        == "leave"
    )
    assert (
        Settings(
            _env_file=None, database_enabled=False, auto_trade_stop_policy="LEAVE"
        ).auto_trade_stop_policy
        == "leave"
    )
    assert (
        Settings(
            _env_file=None, database_enabled=False, auto_trade_stop_policy=""
        ).auto_trade_stop_policy
        == "close"
    )

    with pytest.raises(Exception):
        Settings(
            _env_file=None, database_enabled=False, auto_trade_stop_policy="hold"
        )
