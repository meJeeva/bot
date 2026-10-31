"""Scheduler behaviour for the 5-second entry / 3-second holding cycle.

Everything runs against the mocked MT5 adapter and a virtual monotonic clock,
so no test waits on wall-clock time, and no test places a real order.
"""

from __future__ import annotations

import asyncio
import time

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
from tests.fakes import FakeOrderResult, gold_terminal_with_live_tick


MAGIC = 9001


# ----------------------------------------------------------------------
# Entry cadence and holding duration
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_entry_every_5s_and_exit_after_3s(monkeypatch):
    """T+0 BUY, T+3 close, T+5 BUY, T+8 close - measured on one monotonic clock."""
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, settings = await build_controller(
        fake, auto_trade_max_cycles=2
    )
    events: list[OrderEvent] = []
    instrument_orders(fake, clock, events, MAGIC)

    await controller.start()
    await wait_for_status(controller, {"STOPPED", "ERROR"})

    buys = entries(events)
    sells = exits(events)
    assert len(buys) == 2
    assert len(sells) == 2

    t0 = buys[0].at
    # No normal exit happens before 3 seconds have elapsed.
    assert sells[0].at - t0 == pytest.approx(3.0)
    # The close request targets the ticket of the position just opened.
    assert sells[0].request["position"] is not None
    # The next BUY is 5 seconds after the previous *confirmed fill*.
    assert buys[1].at - t0 == pytest.approx(5.0)
    assert sells[1].at - buys[1].at == pytest.approx(3.0)
    assert controller._completed_cycles == 2


@pytest.mark.asyncio
async def test_holding_timer_starts_at_confirmed_fill(monkeypatch):
    """A late fill confirmation delays the exit; the holding period stays 3s.

    The position is hidden from MT5 reconciliation for 2 virtual seconds after
    the order is submitted, which models an execution/fill latency.
    """
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_max_cycles=1
    )

    events: list[OrderEvent] = []
    original_send = fake.order_send
    original_positions = fake.positions_get
    hidden = {"remaining": None}

    def order_send(request):
        req = request if isinstance(request, dict) else dict(request)
        events.append(
            OrderEvent(
                at=clock.now(),
                request=req,
                open_tickets=[p.ticket for p in fake.positions if p.magic == MAGIC],
            )
        )
        result = original_send(request)
        if "position" not in req:
            hidden["remaining"] = 20  # 20 x 0.1s reconcile polls = 2s
        return result

    def positions_get(symbol=None, ticket=None):
        remaining = hidden["remaining"]
        if remaining is not None:
            if remaining > 0:
                hidden["remaining"] = remaining - 1
                return []
            hidden["remaining"] = None
        return original_positions(symbol=symbol, ticket=ticket)

    fake.order_send = order_send
    fake.positions_get = positions_get

    await controller.start()
    await wait_for_status(controller, {"STOPPED", "ERROR"})

    buys = entries(events)
    sells = exits(events)
    assert len(buys) == 1 and len(sells) == 1

    # Submitted at T, confirmed at T+2, closed 3 seconds after confirmation.
    assert sells[0].at - buys[0].at == pytest.approx(5.0)
    assert sells[0].at - buys[0].at != pytest.approx(3.0)


# ----------------------------------------------------------------------
# Sequential execution and failure handling
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rejected_close_skips_entry_until_position_is_closed(monkeypatch):
    """A rejected close delays the schedule instead of overlapping a new BUY."""
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_max_cycles=2, auto_trade_max_retries=0
    )
    events: list[OrderEvent] = []
    instrument_orders(fake, clock, events, MAGIC)
    # The entry fills; the first close attempt is rejected by the broker.
    fake.order_send_results = [
        FakeOrderResult(retcode=10009),
        FakeOrderResult(retcode=10013, comment="invalid request"),
    ]

    await controller.start()
    await wait_for_status(controller, {"STOPPED", "ERROR"})

    buys = entries(events)
    sells = exits(events)
    assert len(buys) == 2
    # Two close requests for the first position (rejected, then accepted) plus
    # the normal exit of the second cycle.
    assert len(sells) == 3
    assert controller._failed_exits == 1
    # The invariant that matters: no BUY was ever submitted while a strategy
    # position was still open.
    assert all(event.open_tickets == [] for event in buys)
    # The rejected close was retried, and the position closed before (or at the
    # instant of) the next entry. The virtual clock only advances on sleeps, so
    # a same-second ordering is the normal one.
    assert sells[1].at > sells[0].at
    assert buys[1].at >= sells[1].at
    assert buys[1].open_tickets == []


@pytest.mark.asyncio
async def test_ambiguous_entry_is_not_duplicated(monkeypatch):
    """An order that executes but returns no result is adopted, never re-sent."""
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_max_cycles=1
    )
    events: list[OrderEvent] = []
    instrument_orders(fake, clock, events, MAGIC, entry_returns_none=True)

    await controller.start()
    await wait_for_status(controller, {"STOPPED", "ERROR"})

    buys = entries(events)
    assert len(buys) == 1, "an ambiguous submission must not create a duplicate BUY"
    assert len(exits(events)) == 1
    assert controller._position_ticket is None
    assert fake.positions == []
    assert "ambiguous" in (controller._last_entry_result or "")


@pytest.mark.asyncio
async def test_rejected_entry_is_retried_at_the_normal_cadence(monkeypatch):
    """A rejected BUY never fabricates a cycle and never spins in a tight loop."""
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_max_cycles=1
    )
    events: list[OrderEvent] = []
    instrument_orders(fake, clock, events, MAGIC)
    fake.order_send_results = [
        FakeOrderResult(retcode=10016, comment="invalid stops"),
        FakeOrderResult(retcode=10009),
    ]

    await controller.start()
    await wait_for_status(controller, {"STOPPED", "ERROR"})

    buys = entries(events)
    assert len(buys) == 2
    # The retry waited a full entry interval; it did not hammer the broker.
    assert buys[1].at - buys[0].at == pytest.approx(5.0)
    assert controller._failed_entries == 1


# ----------------------------------------------------------------------
# Start / Stop
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_duplicate_start_runs_a_single_loop(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_max_cycles=1000
    )
    events: list[OrderEvent] = []
    instrument_orders(fake, clock, events, MAGIC)

    await controller.start()
    first_task = controller._task
    session = controller._session_id
    assert first_task is not None and not first_task.done()

    second = await controller.start()

    assert second.status == "RUNNING"
    assert controller._task is first_task, "Start must not launch a second scheduler"
    assert controller._session_id == session, "Start must not open a second session"

    await controller.stop()


@pytest.mark.asyncio
async def test_stop_prevents_new_entries_and_closes_the_position(monkeypatch):
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake, auto_trade_max_cycles=1000
    )
    events: list[OrderEvent] = []
    instrument_orders(fake, clock, events, MAGIC)

    await controller.start()
    await wait_for(lambda: len(entries(events)) >= 1)

    status = await controller.stop()

    assert status.status == "STOPPED"
    assert controller._task is None
    assert controller._position_ticket is None
    assert fake.positions == []

    count = len(entries(events))
    await asyncio.sleep(0.05)
    assert len(entries(events)) == count, "the scheduler kept trading after Stop"


@pytest.mark.asyncio
async def test_entry_preflight_refuses_to_run_after_stop(monkeypatch):
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(fake)

    controller._stop_requested = True
    with pytest.raises(RuntimeError, match="Stop requested"):
        await controller._preflight_entry()


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
def test_timing_configuration_defaults():
    settings = Settings(_env_file=None, database_enabled=False)

    assert settings.auto_trade_entry_interval_seconds == 5
    assert settings.auto_trade_holding_duration_seconds == 3
    assert settings.auto_trade_volume == 0.01
    assert settings.auto_trade_max_spread_points == 100


@pytest.mark.parametrize(
    "overrides",
    [
        {"auto_trade_entry_interval_seconds": 0},
        {"auto_trade_holding_duration_seconds": 0},
        {"auto_trade_volume": 0},
        {"auto_trade_max_spread_points": -1},
    ],
)
def test_invalid_timing_configuration_is_rejected(overrides):
    with pytest.raises(Exception):
        Settings(_env_file=None, database_enabled=False, **overrides)


# ----------------------------------------------------------------------
# Existing API surface still works
# ----------------------------------------------------------------------
def test_status_endpoint_reports_the_5s_cycle_and_never_starts_trading():
    from fastapi.testclient import TestClient

    from app.main import create_app

    settings = Settings(
        _env_file=None,
        database_enabled=False,
        log_level="WARNING",
        poll_interval_ms=200,
        auto_trade_max_cycles=5,
        auto_trade_demo_authorized=True,
        live_trading_enabled=False,
    )
    fake = gold_terminal_with_live_tick()
    app = create_app(settings, mt5_module=fake)

    with TestClient(app) as client:
        time.sleep(1)  # let the market monitor publish a live quote
        for _ in range(3):
            status = client.get("/api/auto-trading/status").json()
            assert status["status"] == "STOPPED"
            assert status["timeframe"] == "5s"

        # Polling status (what the browser does) must never place an order.
        assert [call for call in fake.calls if call[0] == "order_send"] == []

        assert client.post("/api/auto-trading/start").status_code == 200
        stopped = client.post("/api/auto-trading/stop").json()

        assert stopped["status"] == "STOPPED"
        assert stopped["position_status"] == "none"
        assert fake.positions == []
