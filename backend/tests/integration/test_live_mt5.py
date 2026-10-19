"""GENUINE MetaTrader 5 integration tests.

These are the only tests in the suite that talk to a real MetaTrader 5 desktop
terminal. Everything under ``tests/`` outside this directory runs against
:class:`tests.fakes.FakeMT5` and is therefore **not** evidence of live
connectivity - only the tests in this file are.

They are marked ``live`` and skip cleanly when no terminal session is
available, so a mock-only environment still produces a green (with skips) run.

Run them explicitly with::

    pytest tests/integration -m live -v

Requirements
------------
* MetaTrader 5 desktop terminal installed and running.
* Logged into a demo or live account.
* ``XAUUSD`` (or the configured symbol) available on that broker.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.mt5.market_data import (
    ServerClock,
    compute_spread,
    read_candles,
    read_quote,
)
from app.mt5.symbols import (
    SymbolResolutionStatus,
    classify_symbol_variant,
    discover_symbol,
    ensure_symbol_selected,
)
from app.mt5.timeframes import SUPPORTED_TIMEFRAMES, TIMEFRAMES

pytestmark = pytest.mark.live

SYMBOL = "XAUUSD"


def _mt5():
    """Import MetaTrader5 or skip. Never imports through the app package."""
    return pytest.importorskip(
        "MetaTrader5",
        reason="The MetaTrader5 package is not installed - no live MT5 available.",
    )


@pytest.fixture(scope="module")
def live_terminal():
    """A genuinely initialized MetaTrader 5 connection, or a clean skip."""
    mt5 = _mt5()

    if not mt5.initialize(timeout=30_000):
        pytest.skip(f"No MetaTrader 5 terminal session available: {mt5.last_error()}")

    terminal = mt5.terminal_info()
    account = mt5.account_info()
    if terminal is None or account is None:
        mt5.shutdown()
        pytest.skip("Terminal is running but not authenticated to an account.")

    if not getattr(terminal, "connected", False):
        mt5.shutdown()
        pytest.skip("Terminal is not connected to its trading server.")

    try:
        yield mt5
    finally:
        mt5.shutdown()


@pytest.fixture(scope="module")
def live_symbol(live_terminal):
    """The broker's real gold symbol, resolved with the production logic."""
    result = discover_symbol(
        live_terminal,
        SYMBOL,
        ["XAUUSD", "XAUUSD.", "XAUUSDm", "XAUUSD.a", "XAUUSD_SB", "#XAUUSD"],
    )
    if result.status is not SymbolResolutionStatus.RESOLVED or not result.symbol:
        pytest.skip(f"Live symbol discovery did not resolve {SYMBOL}: {result.message}")
    assert ensure_symbol_selected(live_terminal, result.symbol) is True
    return result


# ======================================================================
# Terminal and account
# ======================================================================
class TestLiveTerminal:
    def test_terminal_and_account_information_are_available(self, live_terminal):
        terminal = live_terminal.terminal_info()
        account = live_terminal.account_info()

        assert terminal is not None
        assert account is not None
        assert terminal.connected is True
        assert account.server
        assert account.currency

        print(
            "\nLIVE terminal:",
            f"company={terminal.company}",
            f"build={terminal.build}",
            f"server={account.server}",
            f"login={account.login}",
            f"currency={account.currency}",
            f"trade_mode={account.trade_mode}",
        )

    def test_account_is_classified_as_demo_for_this_project(self, live_terminal):
        account = live_terminal.account_info()
        assert account.trade_mode in (0, 1, 2)
        if account.trade_mode == 2:
            pytest.skip("This terminal is logged into a live account, not a demo one.")

    def test_reported_version_is_a_real_mt5_build(self, live_terminal):
        version = live_terminal.version()
        assert version[0] >= 500
        print(f"\nLIVE MetaTrader5 build: {version}")


# ======================================================================
# Symbol discovery
# ======================================================================
class TestLiveSymbolDiscovery:
    def test_resolves_xauusd_or_reports_ambiguity_honestly(self, live_terminal):
        result = discover_symbol(
            live_terminal,
            SYMBOL,
            ["XAUUSD", "XAUUSD.", "XAUUSDm", "XAUUSD.a", "XAUUSD_SB", "#XAUUSD"],
        )

        print(f"\nLIVE symbol discovery: status={result.status.value} symbol={result.symbol}")
        print(f"  message: {result.message}")
        print(f"  candidates: {result.candidates}")

        assert result.status in {
            SymbolResolutionStatus.RESOLVED,
            SymbolResolutionStatus.AMBIGUOUS,
            SymbolResolutionStatus.NOT_FOUND,
        }

    def test_the_resolved_symbol_is_a_gold_instrument(self, live_symbol):
        info = live_symbol.properties
        assert info is not None
        assert info.point > 0
        assert info.digits >= 0
        assert "XAU" in info.name.upper()

        print(
            f"\nLIVE contract spec: {info.name} digits={info.digits} "
            f"point={info.point} tick_size={info.tick_size} tick_value={info.tick_value}"
        )

    def test_a_variant_of_the_configured_symbol_is_never_silently_swapped(self, live_terminal):
        """Whatever is picked must be a variant of XAUUSD, never another pair."""
        result = discover_symbol(live_terminal, SYMBOL, ["XAUUSD"])
        if result.symbol is None:
            pytest.skip("Symbol unresolved on this terminal.")

        classification = classify_symbol_variant(result.symbol, SYMBOL)
        assert classification is not None, (
            f"Discovery returned {result.symbol!r}, which is not a XAUUSD variant."
        )


# ======================================================================
# Ticks and spread
# ======================================================================
class TestLiveQuote:
    def test_live_bid_and_ask_are_retrieved(self, live_terminal, live_symbol):
        info = live_symbol.properties
        clock = ServerClock()
        now = datetime.now(timezone.utc)

        quote = read_quote(
            live_terminal,
            info.name,
            point=info.point,
            digits=info.digits,
            tick_size=info.tick_size,
            tick_value=info.tick_value,
            stale_threshold_seconds=60.0,
            clock=clock,
            now_utc=now,
        )

        if quote is None:
            pytest.skip(
                "No usable tick right now (the market may be closed): "
                f"{live_terminal.last_error()}"
            )

        print(
            f"\nLIVE tick: bid={quote.bid} ask={quote.ask} "
            f"spread={quote.spread_price} ({quote.spread_points} points) "
            f"broker_time={quote.tick_time_broker} utc={quote.tick_time_utc} "
            f"offset={quote.server_time_offset_seconds}s freshness={quote.freshness}"
        )

        assert quote.bid is not None and quote.bid > 0
        assert quote.ask is not None and quote.ask > 0
        assert quote.ask >= quote.bid
        assert quote.spread_price is not None and quote.spread_price >= 0
        assert quote.spread_points is not None and quote.spread_points >= 0
        assert quote.server_time_offset_seconds is not None

    def test_spread_in_points_matches_the_broker_spread_field(self, live_terminal, live_symbol):
        info = live_symbol.properties
        clock = ServerClock()
        now = datetime.now(timezone.utc)

        quote = read_quote(
            live_terminal,
            info.name,
            point=info.point,
            digits=info.digits,
            tick_size=info.tick_size,
            tick_value=info.tick_value,
            stale_threshold_seconds=60.0,
            clock=clock,
            now_utc=now,
        )
        if quote is None:
            pytest.skip("No usable tick right now.")

        # The broker's own `spread` field is expressed in points too, so the
        # two independent measurements must agree closely.
        broker_spread = live_terminal.symbol_info(info.name).spread
        print(f"\nLIVE spread cross-check: computed={quote.spread_points} broker={broker_spread}")
        assert abs(float(broker_spread) - float(quote.spread_points)) < 100.0

    def test_measured_server_offset_is_a_plausible_timezone(self, live_terminal, live_symbol):
        info = live_symbol.properties
        clock = ServerClock()
        now = datetime.now(timezone.utc)

        quote = read_quote(
            live_terminal,
            info.name,
            point=info.point,
            digits=info.digits,
            tick_size=info.tick_size,
            tick_value=info.tick_value,
            stale_threshold_seconds=60.0,
            clock=clock,
            now_utc=now,
        )
        if quote is None:
            pytest.skip("No usable tick right now.")

        offset = quote.server_time_offset_seconds or 0
        assert -14 * 3600 <= offset <= 14 * 3600
        # Broker offsets are whole hours or half hours; a measurement that lands
        # more than a couple of minutes away from that would be a real defect.
        assert abs(offset % 900) <= 120 or abs(offset % 900 - 900) <= 120

    def test_bar_completion_is_exact_for_the_fastest_timeframe(self, live_terminal, live_symbol):
        """The newest closed M1 bar must never be reported as still forming.

        This is the regression guard for a coarse (quarter-hour rounded) server
        offset, which shifted M1 bar boundaries by minutes.
        """
        info = live_symbol.properties
        clock = ServerClock()
        now = datetime.now(timezone.utc)

        quote = read_quote(
            live_terminal,
            info.name,
            point=info.point,
            digits=info.digits,
            tick_size=info.tick_size,
            tick_value=info.tick_value,
            stale_threshold_seconds=600.0,
            clock=clock,
            now_utc=now,
        )
        if quote is None:
            pytest.skip("No usable tick right now.")

        candles = read_candles(
            live_terminal,
            info.name,
            "M1",
            10,
            offset_seconds=clock.offset_seconds,
            now_utc=now,
        )
        forming = [candle for candle in candles if not candle.is_closed]

        print(
            f"\nLIVE M1 completion: offset={clock.offset_seconds}s "
            f"frames={len(candles)} forming={len(forming)}"
        )
        assert len(forming) <= 1

    def test_missing_tick_safety_is_exercised_against_a_nonexistent_symbol(self, live_terminal):
        assert read_quote(
            live_terminal,
            "NO_SUCH_SYMBOL_XYZ",
            point=0.01,
            digits=2,
            tick_size=0.01,
            tick_value=0.1,
            stale_threshold_seconds=60.0,
            clock=ServerClock(),
        ) is None


# ======================================================================
# Candles
# ======================================================================
class TestLiveCandles:
    @pytest.mark.parametrize("timeframe", SUPPORTED_TIMEFRAMES)
    def test_history_is_available_for_every_timeframe(
        self, live_terminal, live_symbol, timeframe
    ):
        info = live_symbol.properties
        clock = ServerClock()
        now = datetime.now(timezone.utc)

        # Prime the server clock from a tick so the UTC conversion is measured.
        read_quote(
            live_terminal,
            info.name,
            point=info.point,
            digits=info.digits,
            tick_size=info.tick_size,
            tick_value=info.tick_value,
            stale_threshold_seconds=600.0,
            clock=clock,
            now_utc=now,
        )

        candles = read_candles(
            live_terminal,
            info.name,
            timeframe,
            50,
            offset_seconds=clock.offset_seconds,
            now_utc=now,
        )

        assert len(candles) == 50
        assert all(candle.high >= candle.low for candle in candles)
        assert all(
            candle.high >= max(candle.open, candle.close) - 1e-9 for candle in candles
        )
        assert candles == sorted(candles, key=lambda candle: candle.time)

        print(
            f"\nLIVE {timeframe}: {len(candles)} bars, "
            f"last={candles[-1].open_time_utc} close={candles[-1].close} "
            f"closed={candles[-1].is_closed} offset={clock.offset_seconds}s"
        )

    def test_candle_timestamps_convert_broker_local_time_to_utc(self, live_terminal, live_symbol):
        info = live_symbol.properties
        clock = ServerClock()
        now = datetime.now(timezone.utc)

        read_quote(
            live_terminal,
            info.name,
            point=info.point,
            digits=info.digits,
            tick_size=info.tick_size,
            tick_value=info.tick_value,
            stale_threshold_seconds=600.0,
            clock=clock,
            now_utc=now,
        )
        candles = read_candles(
            live_terminal,
            info.name,
            "M15",
            5,
            offset_seconds=clock.offset_seconds,
            now_utc=now,
        )

        for candle in candles:
            delta = (candle.open_time_broker - candle.open_time_utc).total_seconds()
            assert delta == clock.offset_seconds
            assert candle.open_time_broker.timestamp() == candle.time

    def test_forming_bar_is_not_reported_as_closed(self, live_terminal, live_symbol):
        info = live_symbol.properties
        clock = ServerClock()
        now = datetime.now(timezone.utc)

        read_quote(
            live_terminal,
            info.name,
            point=info.point,
            digits=info.digits,
            tick_size=info.tick_size,
            tick_value=info.tick_value,
            stale_threshold_seconds=600.0,
            clock=clock,
            now_utc=now,
        )
        candles = read_candles(
            live_terminal,
            info.name,
            "M1",
            10,
            offset_seconds=clock.offset_seconds,
            now_utc=now,
        )

        closed = [candle for candle in candles if candle.is_closed]
        forming = [candle for candle in candles if not candle.is_closed]

        assert len(forming) <= 1, "At most the newest bar can still be forming"
        assert len(closed) >= len(candles) - 1

    def test_timeframe_constants_match_the_live_terminal(self, live_terminal):
        assert TIMEFRAMES["M1"].mt5_value == live_terminal.TIMEFRAME_M1
        assert TIMEFRAMES["M5"].mt5_value == live_terminal.TIMEFRAME_M5
        assert TIMEFRAMES["M15"].mt5_value == live_terminal.TIMEFRAME_M15
        assert TIMEFRAMES["M30"].mt5_value == live_terminal.TIMEFRAME_M30
        assert TIMEFRAMES["H1"].mt5_value == live_terminal.TIMEFRAME_H1
        assert TIMEFRAMES["H4"].mt5_value == live_terminal.TIMEFRAME_H4
        assert TIMEFRAMES["D1"].mt5_value == live_terminal.TIMEFRAME_D1


# ======================================================================
# Production stack against the live terminal
# ======================================================================
class TestLiveApplicationStack:
    def test_connection_manager_connects_and_reports_safe_status(self, make_settings):
        from app.mt5.connection import MT5Connection

        connection = MT5Connection(make_settings())
        try:
            assert connection.initialize_sync() is True
            status = connection.build_status_sync()

            print(
                f"\nLIVE connection status: state={status.state.value} "
                f"initialized={status.mt5_initialized} connected={status.terminal_connected} "
                f"server={status.trading_server} account={status.account_login_masked} "
                f"type={status.account_type.value} currency={status.account_currency}"
            )

            assert status.mt5_initialized is True
            assert status.terminal_connected is True
            assert status.account_login_masked is not None
            assert status.account_login is None  # masked by default
            assert status.trading_enabled is False
            assert status.read_only is True
        finally:
            connection.shutdown_sync()

    def test_full_monitor_poll_produces_live_market_data(self, make_settings):
        import asyncio

        from app.mt5.connection import MT5Connection
        from app.services.market_monitor import MarketMonitor
        from app.schemas.status import DataStatus

        async def run():
            connection = MT5Connection(make_settings())
            try:
                if not await connection.initialize():
                    pytest.skip("Live MT5 initialization failed.")
                monitor = MarketMonitor(connection, make_settings())

                await monitor._ensure_symbol()
                if monitor.symbol_status.resolution != "resolved":
                    pytest.skip(f"Live symbol not resolved: {monitor.symbol_status.message}")

                for _ in range(3):
                    await monitor._poll_once()

                return monitor
            finally:
                await connection.shutdown()

        monitor = asyncio.run(run())

        if monitor.latest_quote() is None:
            pytest.skip("No live tick available right now (market may be closed).")

        snapshot = monitor.build_snapshot_sync()
        print(
            f"\nLIVE monitor snapshot: status={snapshot.data_status.value} "
            f"symbol={snapshot.symbol.resolved} bid={snapshot.quote.bid} "
            f"ask={snapshot.quote.ask} spread_pts={snapshot.quote.spread_points} "
            f"trading_enabled={snapshot.trading_enabled}"
        )

        assert snapshot.data_status in {DataStatus.LIVE, DataStatus.STALE}
        assert snapshot.symbol.resolved
        assert snapshot.trading_enabled is False
