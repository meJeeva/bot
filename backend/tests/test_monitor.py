"""Market monitor behaviour.

The monitor is the piece that must stay alive through terminal failures and
must never present stale prices as live, so most of these tests drive
``_poll_once()`` directly with a controlled clock.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.config import Settings
from app.mt5.connection import MT5Connection
from app.mt5.timeframes import TIMEFRAME_ORDER
from app.schemas.status import DataStatus
from app.services import market_monitor as monitor_module
from app.services.market_monitor import MarketMonitor
from tests.fakes import (
    DEFAULT_SERVER_OFFSET_SECONDS,
    FakeMT5,
    FakeSymbolInfo,
    FakeTick,
    broker_time,
    gold_terminal_with_live_tick,
)


def build(**overrides) -> Settings:
    overrides.setdefault("database_enabled", False)
    overrides.setdefault("log_level", "WARNING")
    return Settings(_env_file=None, **overrides)


async def ready_monitor(settings: Settings, fake: FakeMT5) -> tuple[MT5Connection, MarketMonitor]:
    connection = MT5Connection(settings, mt5_module=fake)
    assert await connection.initialize() is True
    return connection, MarketMonitor(connection, settings)


class TestSymbolResolutionInMonitor:
    async def test_resolves_xauusd_and_publishes_the_contract_spec(self):
        fake = gold_terminal_with_live_tick()
        _, monitor = await ready_monitor(build(), fake)

        await monitor._ensure_symbol()

        status = monitor.symbol_status
        assert status.resolution == "resolved"
        assert status.resolved == "XAUUSD"
        assert status.requires_configuration is False
        assert status.info is not None
        assert status.info.digits == 2
        assert status.info.point == 0.01

    async def test_ambiguous_symbol_is_surfaced_and_requires_configuration(self):
        fake = FakeMT5(
            symbols=[FakeSymbolInfo("XAUUSDm"), FakeSymbolInfo("XAUUSDc")],
            ticks={"XAUUSDm": FakeTick(time=broker_time())},
        )
        _, monitor = await ready_monitor(build(), fake)

        await monitor._ensure_symbol()

        status = monitor.symbol_status
        assert status.resolution == "ambiguous"
        assert status.requires_configuration is True
        assert sorted(status.candidates) == ["XAUUSDc", "XAUUSDm"]
        assert status.resolved is None

    async def test_monitor_does_not_poll_prices_while_the_symbol_is_unresolved(self):
        fake = FakeMT5(symbols=[FakeSymbolInfo("XAUEUR")])
        _, monitor = await ready_monitor(build(), fake)

        await monitor._poll_once()

        assert monitor.latest_quote() is None
        assert monitor.data_status is DataStatus.UNAVAILABLE
        assert "symbol_info_tick" not in fake.call_names()

    async def test_symbol_is_added_to_market_watch(self):
        fake = gold_terminal_with_live_tick()
        fake.symbol_info("XAUUSD").visible = False
        _, monitor = await ready_monitor(build(), fake)

        await monitor._ensure_symbol()

        assert "XAUUSD" in fake.selected


class TestLivePolling:
    async def test_a_live_tick_produces_a_live_quote(self):
        fake = gold_terminal_with_live_tick(bid=4185.58, ask=4186.14)
        _, monitor = await ready_monitor(build(), fake)

        await monitor._poll_once()

        quote = monitor.latest_quote()
        assert quote is not None
        assert quote.bid == 4185.58
        assert quote.ask == 4186.14
        assert quote.spread_points == pytest.approx(56.0)
        assert quote.freshness == "live"
        assert monitor.data_status is DataStatus.LIVE

    async def test_monitor_measures_the_server_offset_from_the_tick(self):
        fake = gold_terminal_with_live_tick()
        _, monitor = await ready_monitor(build(), fake)

        await monitor._poll_once()

        quote = monitor.latest_quote()
        assert quote is not None
        assert abs(quote.server_time_offset_seconds - DEFAULT_SERVER_OFFSET_SECONDS) <= 1

    async def test_repeated_polls_do_not_lose_the_quote(self):
        fake = gold_terminal_with_live_tick()
        _, monitor = await ready_monitor(build(), fake)

        for _ in range(3):
            await monitor._poll_once()

        assert monitor.latest_quote() is not None
        assert monitor.data_status is DataStatus.LIVE


class TestStaleness:
    async def test_frozen_feed_is_reported_as_stale_not_live(self, monkeypatch):
        fake = gold_terminal_with_live_tick()
        _, monitor = await ready_monitor(build(), fake)

        clock_holder = {"now": datetime.now(timezone.utc)}
        monkeypatch.setattr(monitor_module, "_utcnow", lambda: clock_holder["now"])

        await monitor._poll_once()
        assert monitor.data_status is DataStatus.LIVE

        # An hour passes and the terminal keeps returning the same tick.
        clock_holder["now"] = clock_holder["now"] + timedelta(hours=1)
        await monitor._poll_once()

        quote = monitor.latest_quote()
        assert quote is not None
        assert quote.is_stale is True
        assert quote.freshness == "stale"
        assert quote.age_seconds is not None and quote.age_seconds > 3000
        assert monitor.data_status is DataStatus.STALE

    async def test_a_vanished_tick_does_not_clear_the_last_quote(self, monkeypatch):
        fake = gold_terminal_with_live_tick()
        _, monitor = await ready_monitor(build(), fake)

        clock_holder = {"now": datetime.now(timezone.utc)}
        monkeypatch.setattr(monitor_module, "_utcnow", lambda: clock_holder["now"])

        await monitor._poll_once()
        assert monitor.latest_quote() is not None

        fake.set_tick("XAUUSD", None)
        clock_holder["now"] = clock_holder["now"] + timedelta(minutes=5)
        await monitor._poll_once()

        # The last known price is retained but flagged, never republished as live.
        assert monitor.latest_quote() is not None
        assert monitor.data_status is DataStatus.STALE
        assert monitor.last_error is not None

    async def test_snapshot_recomputes_age_even_without_a_new_poll(self, monkeypatch):
        fake = gold_terminal_with_live_tick()
        _, monitor = await ready_monitor(build(), fake)

        clock_holder = {"now": datetime.now(timezone.utc)}
        monkeypatch.setattr(monitor_module, "_utcnow", lambda: clock_holder["now"])

        await monitor._poll_once()
        clock_holder["now"] = clock_holder["now"] + timedelta(hours=2)

        snapshot = monitor.build_snapshot_sync()
        assert snapshot.data_status is DataStatus.STALE
        assert snapshot.quote is not None
        assert snapshot.quote.is_stale is True


class TestCandleCaching:
    async def test_all_seven_timeframes_are_cached(self):
        fake = gold_terminal_with_live_tick(with_all_timeframes=True)
        _, monitor = await ready_monitor(build(), fake)

        await monitor._ensure_symbol()
        for _ in range(len(TIMEFRAME_ORDER) + 1):
            await monitor._refresh_next_timeframe()

        for name in TIMEFRAME_ORDER:
            series = monitor.candle_series(name)
            assert series is not None, name
            assert series.count > 0

    async def test_snapshot_carries_all_seven_timeframes(self):
        fake = gold_terminal_with_live_tick(with_all_timeframes=True)
        _, monitor = await ready_monitor(build(), fake)
        await monitor._ensure_symbol()
        for _ in range(len(TIMEFRAME_ORDER) + 1):
            await monitor._refresh_next_timeframe()

        snapshot = monitor.build_snapshot_sync()

        assert sorted(snapshot.timeframes) == sorted(TIMEFRAME_ORDER)
        assert snapshot.timeframes["M15"].latest_closed is not None

    async def test_get_candles_trims_to_the_requested_limit(self):
        fake = gold_terminal_with_live_tick(with_all_timeframes=True, history=400)
        _, monitor = await ready_monitor(build(), fake)
        await monitor._ensure_symbol()

        series = await monitor.get_candles("M15", 10)

        assert len(series.candles) == 10
        assert series.count == 10
        assert series.requested_limit == 10

    async def test_only_one_timeframe_is_refreshed_per_poll(self):
        fake = gold_terminal_with_live_tick(with_all_timeframes=True)
        _, monitor = await ready_monitor(build(), fake)
        await monitor._ensure_symbol()

        await monitor._refresh_next_timeframe()

        rate_calls = [c for c in fake.calls if c[0] == "copy_rates_from_pos"]
        assert len(rate_calls) == 1

    async def test_refresh_error_is_recorded_not_raised(self):
        # This fake has a live tick but no candle history at all.
        fake = gold_terminal_with_live_tick()
        _, monitor = await ready_monitor(build(), fake)
        await monitor._ensure_symbol()

        await monitor._refresh_next_timeframe()  # must not raise

        assert monitor.candle_series("M1") is None
        assert monitor.build_snapshot_sync().timeframes["M1"].error is not None


class TestSubscriptions:
    async def test_subscriber_receives_a_snapshot_after_a_poll(self):
        fake = gold_terminal_with_live_tick()
        _, monitor = await ready_monitor(build(), fake)
        queue = monitor.subscribe()

        await monitor._poll_once()

        snapshot = queue.get_nowait()
        assert snapshot.sequence >= 1
        assert snapshot.quote is not None
        assert snapshot.trading_enabled is False
        monitor.unsubscribe(queue)
        assert monitor.subscriber_count == 0

    async def test_slow_client_keeps_the_newest_frame_only(self):
        fake = gold_terminal_with_live_tick()
        _, monitor = await ready_monitor(build(ws_max_queue=1), fake)
        queue = monitor.subscribe()

        await monitor._publish(force=True)
        first_sequence = monitor.sequence
        await monitor._publish(force=True)

        assert queue.qsize() == 1
        latest = queue.get_nowait()
        assert latest.sequence == monitor.sequence > first_sequence

    async def test_publishing_without_subscribers_is_cheap(self):
        fake = gold_terminal_with_live_tick()
        _, monitor = await ready_monitor(build(), fake)

        await monitor._publish(force=True)

        assert monitor.subscriber_count == 0


class TestLifecycle:
    async def test_starting_twice_creates_a_single_loop(self):
        fake = gold_terminal_with_live_tick(with_all_timeframes=True)
        settings = build(poll_interval_ms=60000)
        _, monitor = await ready_monitor(settings, fake)

        try:
            await monitor.start()
            first_task = monitor._task
            await monitor.start()
            assert monitor._task is first_task
            assert len([t for t in asyncio.all_tasks() if t.get_name() == "market-monitor"]) == 1
        finally:
            await monitor.stop()

    async def test_stop_cancels_the_loop(self):
        fake = gold_terminal_with_live_tick(with_all_timeframes=True)
        settings = build(poll_interval_ms=60000)
        _, monitor = await ready_monitor(settings, fake)

        await monitor.start()
        assert monitor.running is True

        await monitor.stop()
        assert monitor.running is False

    async def test_stop_without_start_is_safe(self):
        fake = gold_terminal_with_live_tick()
        _, monitor = await ready_monitor(build(), fake)
        await monitor.stop()
        assert monitor.running is False


class TestFailureRecovery:
    async def test_monitor_survives_a_terminal_that_never_connected(self):
        fake = FakeMT5(initialize_ok=False, last_error_value=(-6, "Authorization failed"))
        connection = MT5Connection(build(), mt5_module=fake)
        await connection.initialize()
        monitor = MarketMonitor(connection, build())

        await monitor._poll_once()  # must not raise

        assert monitor.latest_quote() is None
        assert monitor.data_status is DataStatus.UNAVAILABLE
        assert monitor.build_snapshot_sync().connection.state.value in {"error", "reconnecting"}

    async def test_monitor_recovers_after_the_terminal_returns(self):
        fake = gold_terminal_with_live_tick()
        settings = build(reconnect_initial_delay_seconds=0.01)
        _, monitor = await ready_monitor(settings, fake)
        await monitor._poll_once()
        assert monitor.data_status is DataStatus.LIVE

        # Terminal drops out.
        monitor.connection.register_disconnect("terminal closed")
        fake.terminal.connected = False
        await monitor._poll_once()
        assert monitor.data_status is DataStatus.STALE

        # Terminal comes back and the retry window has elapsed.
        fake.terminal.connected = True
        monitor.connection._next_reconnect_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await monitor._poll_once()

        assert monitor.latest_quote() is not None
        assert monitor.data_status is DataStatus.LIVE

    async def test_reconnect_revalidates_the_symbol(self):
        fake = gold_terminal_with_live_tick()
        settings = build(reconnect_initial_delay_seconds=0.01)
        _, monitor = await ready_monitor(settings, fake)
        await monitor._poll_once()

        monitor.connection.register_disconnect("terminal closed")
        fake.terminal.connected = False
        monitor.connection._next_reconnect_at = datetime.now(timezone.utc) - timedelta(seconds=1)

        await monitor._poll_once()

        assert monitor.symbol_status.resolved == "XAUUSD"

    async def test_repeated_failures_schedule_a_disconnect(self):
        fake = gold_terminal_with_live_tick()
        _, monitor = await ready_monitor(build(), fake)
        await monitor._poll_once()

        fake.set_tick("XAUUSD", None)
        for _ in range(3):
            await monitor._poll_once()

        assert monitor.connection.build_status_sync().reconnect_attempts >= 1


class TestSnapshotContract:
    async def test_snapshot_never_claims_trading_is_enabled(self):
        fake = gold_terminal_with_live_tick(with_all_timeframes=True)
        _, monitor = await ready_monitor(build(), fake)
        await monitor._poll_once()

        snapshot = monitor.build_snapshot_sync()

        assert snapshot.trading_enabled is False
        assert snapshot.read_only is True
        assert snapshot.connection.read_only is True
        assert snapshot.type == "snapshot"

    async def test_snapshot_before_any_poll_is_unavailable_but_valid(self):
        fake = gold_terminal_with_live_tick()
        _, monitor = await ready_monitor(build(), fake)

        snapshot = monitor.build_snapshot_sync()

        assert snapshot.data_status is DataStatus.UNAVAILABLE
        assert snapshot.quote is None
        assert snapshot.connection.state.value == "disconnected"


class TestPersistence:
    """The SQLite path must be exercised with persistence switched ON.

    A keyword/positional mismatch here previously threw inside the poll loop and
    stopped snapshots from ever being published.
    """

    async def test_poll_persists_connection_events_and_quotes(self, tmp_path):
        from app.storage import StatusStore

        store = StatusStore(tmp_path / "status.db")
        assert store.initialize() is True

        fake = gold_terminal_with_live_tick(with_all_timeframes=True)
        settings = build(database_enabled=True)
        connection = MT5Connection(settings, mt5_module=fake)
        assert await connection.initialize() is True
        monitor = MarketMonitor(connection, settings, store=store)

        await monitor._poll_once()
        await monitor._poll_once()

        events, snapshots = store.counts()
        assert events >= 1
        assert snapshots == 1  # sampled at most once per second

        status_events = store.recent_connection_events()
        assert status_events[0]["symbol"] == "XAUUSD"
        store.close()

    async def test_poll_still_publishes_when_persistence_raises(self):
        class ExplodingStore:
            enabled = True

            def record_quote(self, quote):  # noqa: ANN001, ARG002
                raise RuntimeError("disk on fire")

            def record_connection_event(self, status, *, symbol=None):  # noqa: ANN001, ARG002
                raise RuntimeError("disk on fire")

        fake = gold_terminal_with_live_tick()
        settings = build(database_enabled=True)
        connection = MT5Connection(settings, mt5_module=fake)
        assert await connection.initialize() is True
        monitor = MarketMonitor(connection, settings, store=ExplodingStore())  # type: ignore[arg-type]

        queue = monitor.subscribe()
        await monitor._poll_once()  # must not raise

        assert queue.qsize() == 1
        assert monitor.latest_quote() is not None
        assert monitor.data_status is DataStatus.LIVE
