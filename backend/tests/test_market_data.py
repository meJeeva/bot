"""Market-data retrieval: ticks, spreads, candles and broker time.

These are the tests that encode the two rules most likely to be got wrong:

* spread must be reported in **price units** and in **points**, and the two
  must never be conflated (XAUUSD: 0.56 price difference = 56 points at a
  0.01 point size); and
* MetaTrader bar/tick timestamps are **broker server local time**, so the UTC
  value has to be derived from a *measured* offset.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.mt5.market_data import (
    MarketDataError,
    ServerClock,
    broker_to_utc,
    compute_spread,
    read_candles,
    read_quote,
)
from app.schemas.market import Candle, Quote
from tests.fakes import (
    DEFAULT_SERVER_OFFSET_SECONDS,
    TIMEFRAME_M15,
    FakeMT5,
    FakeSymbolInfo,
    FakeTick,
    broker_time,
    make_rates,
    utc_now,
)

M15_SECONDS = 900


def anchored_clock(offset_seconds: int, at: datetime) -> ServerClock:
    """A clock whose offset has already been measured - as after the first poll."""
    clock = ServerClock()
    clock.offset_seconds = offset_seconds
    clock.measured_at = at
    return clock


def m15_rows(count: int, now_utc: datetime, offset: int = DEFAULT_SERVER_OFFSET_SECONDS):
    """Ordered M15 rows whose final bar is still forming."""
    broker_now = int(now_utc.timestamp()) + offset
    last_open = (broker_now // M15_SECONDS) * M15_SECONDS
    return [
        (
            last_open - (count - 1 - index) * M15_SECONDS,
            2400.0 + index,
            2401.0 + index,
            2399.0 + index,
            2400.5 + index,
            100 + index,
            12,
            0,
        )
        for index in range(count)
    ]


# ======================================================================
# Broker time
# ======================================================================
class TestServerClock:
    def test_measures_a_utc_plus_three_server_offset(self):
        clock = ServerClock()
        now = datetime(2026, 10, 12, 5, 0, 0, tzinfo=timezone.utc)
        broker_wall_clock = datetime(2026, 10, 12, 8, 0, 0, tzinfo=timezone.utc)

        offset = clock.observe(int(broker_wall_clock.timestamp()), now)

        assert offset == 10800
        assert clock.measured is True

    def test_offset_is_measured_to_the_second(self):
        """Coarse rounding would shift bar boundaries and misreport completion."""
        clock = ServerClock()
        now = datetime(2026, 10, 12, 5, 0, 0, tzinfo=timezone.utc)
        raw = int((now + timedelta(hours=3, seconds=7)).timestamp())

        assert clock.observe(raw, now) == 10807

    def test_sub_second_latency_does_not_leak_into_the_offset(self):
        clock = ServerClock()
        now = datetime(2026, 10, 12, 5, 0, 0, 350_000, tzinfo=timezone.utc)
        raw = int((now + timedelta(hours=3)).timestamp())

        offset = clock.observe(raw, now)
        assert offset == 10800 or offset == 10801

    def test_a_frozen_feed_does_not_re_anchor_the_offset(self):
        """The whole point: a stalled feed must not look current again."""
        clock = ServerClock(refresh_seconds=0)
        t0 = datetime(2026, 10, 12, 5, 0, 0, tzinfo=timezone.utc)
        raw = int((t0 + timedelta(hours=3)).timestamp())

        assert clock.observe(raw, t0) == 10800
        # An hour passes and the broker timestamp has not moved.
        assert clock.observe(raw, t0 + timedelta(hours=1)) == 10800

    def test_offset_is_re_measured_when_the_feed_advances(self):
        clock = ServerClock(refresh_seconds=0)
        t0 = datetime(2026, 10, 12, 5, 0, 0, tzinfo=timezone.utc)

        assert clock.observe(int((t0 + timedelta(hours=3)).timestamp()), t0) == 10800
        later = int((t0 + timedelta(hours=3, seconds=30)).timestamp())
        assert clock.observe(later, t0 + timedelta(seconds=30)) == 10800

    def test_detects_a_real_offset_change(self):
        clock = ServerClock(refresh_seconds=0)
        t0 = datetime(2026, 10, 12, 5, 0, 0, tzinfo=timezone.utc)

        clock.observe(int((t0 + timedelta(hours=3)).timestamp()), t0)
        # The server's clock jumps forward by a further hour.
        clock.observe(int((t0 + timedelta(hours=6)).timestamp()), t0 + timedelta(hours=2))

        assert clock.offset_seconds == 14400
        assert clock.drift_detected is True

    def test_implausible_offset_is_ignored(self):
        clock = ServerClock()
        now = datetime(2026, 10, 12, 5, 0, 0, tzinfo=timezone.utc)
        raw = int((now + timedelta(hours=40)).timestamp())

        assert clock.observe(raw, now) == 0
        assert clock.measured is False

    def test_missing_timestamp_keeps_the_existing_offset(self):
        clock = anchored_clock(10800, utc_now())
        assert clock.observe(None, utc_now()) == 10800
        assert clock.observe(0, utc_now()) == 10800

    def test_reset_clears_the_measurement(self):
        clock = anchored_clock(10800, utc_now())
        clock.reset()
        assert clock.offset_seconds == 0
        assert clock.measured is False

    def test_broker_to_utc_subtracts_the_offset(self):
        actual = broker_to_utc(1791795000, 10800)
        as_utc = datetime.fromtimestamp(1791795000, tz=timezone.utc)
        assert actual == as_utc - timedelta(seconds=10800)


# ======================================================================
# Spread
# ======================================================================
class TestSpread:
    def test_xauusd_price_difference_versus_points(self):
        price, points = compute_spread(4185.58, 4186.14, 0.01)
        assert price == pytest.approx(0.56)
        assert points == pytest.approx(56.0)

    def test_five_digit_fx_point_size(self):
        price, points = compute_spread(1.10000, 1.10012, 0.00001)
        assert price == pytest.approx(0.00012)
        assert points == pytest.approx(12.0)

    def test_zero_spread_is_reported_as_zero(self):
        price, points = compute_spread(2400.0, 2400.0, 0.01)
        assert price == 0.0
        assert points == 0.0

    def test_invalid_point_size_is_rejected(self):
        with pytest.raises(MarketDataError):
            compute_spread(1.0, 1.1, 0.0)


# ======================================================================
# Ticks
# ======================================================================
class TestReadQuote:
    def _read(self, mt5: FakeMT5, **overrides):
        now = overrides.pop("now_utc", utc_now())
        clock = overrides.pop("clock", anchored_clock(DEFAULT_SERVER_OFFSET_SECONDS, now))
        defaults = dict(
            point=0.01,
            digits=2,
            tick_size=0.01,
            tick_value=0.1,
            stale_threshold_seconds=20.0,
        )
        defaults.update(overrides)
        return read_quote(mt5, "XAUUSD", clock=clock, now_utc=now, **defaults)

    def test_returns_a_complete_live_quote(self):
        now = utc_now()
        mt5 = FakeMT5()
        mt5.set_tick(
            "XAUUSD",
            FakeTick(time=broker_time(), bid=4185.58, ask=4186.14),
        )

        quote = self._read(mt5, now_utc=now)

        assert quote is not None
        assert quote.bid == pytest.approx(4185.58)
        assert quote.ask == pytest.approx(4186.14)
        assert quote.spread_price == pytest.approx(0.56)
        assert quote.spread_points == pytest.approx(56.0)
        assert quote.freshness == "live"
        assert quote.is_stale is False
        assert abs(quote.server_time_offset_seconds - 10800) <= 1

    def test_tick_time_is_converted_from_broker_time_to_utc(self):
        now = utc_now()
        mt5 = FakeMT5()
        mt5.set_tick("XAUUSD", FakeTick(time=broker_time(), bid=2400.0, ask=2400.5))

        quote = self._read(mt5, now_utc=now)
        assert quote is not None
        assert quote.tick_time_broker is not None
        assert quote.tick_time_utc is not None
        assert (
            quote.tick_time_broker - quote.tick_time_utc
        ).total_seconds() == pytest.approx(10800, abs=1)

    def test_last_price_of_zero_is_reported_as_unavailable(self):
        mt5 = FakeMT5()
        mt5.set_tick("XAUUSD", FakeTick(time=broker_time(), bid=2400.0, ask=2400.5, last=0.0))

        quote = self._read(mt5)
        assert quote is not None
        assert quote.last is None

    def test_a_real_last_price_is_kept(self):
        mt5 = FakeMT5()
        mt5.set_tick("XAUUSD", FakeTick(time=broker_time(), bid=2400.0, ask=2400.5, last=2400.2))

        quote = self._read(mt5)
        assert quote is not None
        assert quote.last == pytest.approx(2400.2)

    def test_missing_tick_returns_none(self):
        mt5 = FakeMT5()
        mt5.set_tick("XAUUSD", None)
        assert self._read(mt5) is None

    def test_zero_bid_is_discarded_not_replaced(self):
        mt5 = FakeMT5()
        mt5.set_tick("XAUUSD", FakeTick(time=broker_time(), bid=0.0, ask=2400.5))
        assert self._read(mt5) is None

    def test_zero_ask_is_discarded(self):
        mt5 = FakeMT5()
        mt5.set_tick("XAUUSD", FakeTick(time=broker_time(), bid=2400.0, ask=0.0))
        assert self._read(mt5) is None

    def test_inverted_quote_is_discarded(self):
        mt5 = FakeMT5()
        mt5.set_tick("XAUUSD", FakeTick(time=broker_time(), bid=2401.0, ask=2400.0))
        assert self._read(mt5) is None

    def test_stale_tick_is_marked_stale(self):
        now = utc_now()
        mt5 = FakeMT5()
        # Broker timestamp frozen 30 minutes ago.
        mt5.set_tick(
            "XAUUSD",
            FakeTick(time=broker_time(delta_seconds=-1800), bid=2400.0, ask=2400.5),
        )

        quote = self._read(mt5, now_utc=now)

        assert quote is not None
        assert quote.is_stale is True
        assert quote.freshness == "stale"
        assert quote.age_seconds == pytest.approx(1800, abs=2)

    def test_quote_schema_rejects_an_inconsistent_spread(self):
        with pytest.raises(ValidationError):
            Quote(
                symbol="XAUUSD",
                bid=2400.0,
                ask=2400.5,
                spread_price=9.99,
                point=0.01,
                digits=2,
            )

    def test_quote_schema_fills_spread_when_omitted(self):
        quote = Quote(symbol="XAUUSD", bid=2400.0, ask=2400.5, point=0.01, digits=2)
        assert quote.spread_price == pytest.approx(0.5)


# ======================================================================
# Candles
# ======================================================================
class TestReadCandles:
    def test_reads_m15_bars_with_the_central_timeframe_constant(self):
        now = utc_now()
        mt5 = FakeMT5()
        mt5.set_rates("XAUUSD", TIMEFRAME_M15, make_rates(m15_rows(5, now)))

        candles = read_candles(
            mt5, "XAUUSD", "M15", 5, offset_seconds=10800, now_utc=now
        )

        assert len(candles) == 5
        call = next(c for c in mt5.calls if c[0] == "copy_rates_from_pos")
        assert call[1][1] == TIMEFRAME_M15

    def test_distinguishes_the_forming_bar_from_the_closed_bar(self):
        now = utc_now()
        mt5 = FakeMT5()
        mt5.set_rates("XAUUSD", TIMEFRAME_M15, make_rates(m15_rows(5, now)))

        candles = read_candles(mt5, "XAUUSD", "M15", 5, offset_seconds=10800, now_utc=now)

        assert candles[-1].is_closed is False
        assert all(candle.is_closed for candle in candles[:-1])

    def test_candle_times_are_broker_local_plus_utc(self):
        now = utc_now()
        mt5 = FakeMT5()
        mt5.set_rates("XAUUSD", TIMEFRAME_M15, make_rates(m15_rows(3, now)))

        candles = read_candles(mt5, "XAUUSD", "M15", 3, offset_seconds=10800, now_utc=now)

        for candle in candles:
            assert candle.open_time_broker - candle.open_time_utc == timedelta(seconds=10800)
            assert candle.open_time_broker.timestamp() == candle.time

    def test_invalid_ohlc_bar_is_dropped_and_the_rest_kept(self):
        now = utc_now()
        rows = m15_rows(5, now)
        rows[1] = (rows[1][0], 2400.0, 2390.0, 2410.0, 2400.0, 5, 12, 0)  # high < low
        mt5 = FakeMT5()
        mt5.set_rates("XAUUSD", TIMEFRAME_M15, make_rates(rows))

        candles = read_candles(mt5, "XAUUSD", "M15", 5, offset_seconds=10800, now_utc=now)

        assert len(candles) == 4
        assert all(candle.high >= candle.low for candle in candles)

    def test_series_of_only_invalid_bars_raises(self):
        now = utc_now()
        rows = [(int(now.timestamp()) - i * 900, 1.0, 0.5, 2.0, 1.0, 1, 0, 0) for i in range(3)]
        mt5 = FakeMT5()
        mt5.set_rates("XAUUSD", TIMEFRAME_M15, make_rates(rows))

        with pytest.raises(MarketDataError) as info:
            read_candles(mt5, "XAUUSD", "M15", 3, offset_seconds=10800, now_utc=now)
        assert info.value.code == "invalid_candle_data"

    def test_missing_history_raises(self):
        mt5 = FakeMT5()
        with pytest.raises(MarketDataError) as info:
            read_candles(mt5, "XAUUSD", "M15", 5, offset_seconds=0, now_utc=utc_now())
        assert info.value.code == "no_candle_data"

    def test_empty_history_raises(self):
        mt5 = FakeMT5()
        mt5.set_rates("XAUUSD", TIMEFRAME_M15, make_rates([]))
        with pytest.raises(MarketDataError) as info:
            read_candles(mt5, "XAUUSD", "M15", 5, offset_seconds=0, now_utc=utc_now())
        assert info.value.code == "empty_candle_data"

    def test_non_positive_limit_is_rejected(self):
        mt5 = FakeMT5()
        with pytest.raises(MarketDataError) as info:
            read_candles(mt5, "XAUUSD", "M15", 0, offset_seconds=0, now_utc=utc_now())
        assert info.value.code == "invalid_limit"

    def test_an_exception_from_mt5_is_wrapped(self):
        class BoomMT5(FakeMT5):
            def copy_rates_from_pos(self, *args, **kwargs):  # noqa: D102
                raise RuntimeError("ipc exploded")

        with pytest.raises(MarketDataError) as info:
            read_candles(BoomMT5(), "XAUUSD", "M15", 5, offset_seconds=0, now_utc=utc_now())
        assert info.value.code == "mt5_call_failed"

    def test_supports_every_one_of_the_seven_timeframes(self):
        now = utc_now()
        spec_seconds = {
            1: 60, 5: 300, 15: 900, 30: 1800, 16385: 3600, 16388: 14400, 16408: 86400
        }
        mt5 = FakeMT5()
        for mt5_value, step in spec_seconds.items():
            rows = [
                (int(now.timestamp()) - index * step, 1.0 + index, 2.0 + index, 0.5 + index, 1.5 + index, 1, 0, 0)
                for index in range(3)
            ]
            mt5.set_rates("XAUUSD", mt5_value, make_rates(rows))

        for name in ("M1", "M5", "M15", "M30", "H1", "H4", "D1"):
            candles = read_candles(
                mt5, "XAUUSD", name, 3, offset_seconds=0, now_utc=now
            )
            assert len(candles) == 3


class TestCandleSchema:
    def _candle(self, **overrides):
        base = dict(
            time=1791792000,
            open_time_broker=datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc),
            open_time_utc=datetime(2026, 10, 12, 5, 0, tzinfo=timezone.utc),
            open=2400.0,
            high=2401.0,
            low=2399.0,
            close=2400.5,
        )
        base.update(overrides)
        return Candle(**base)

    def test_valid_candle(self):
        candle = self._candle()
        assert candle.is_closed is True
        assert candle.tick_volume == 0

    def test_rejects_high_below_low(self):
        with pytest.raises(ValidationError):
            self._candle(high=2398.0, low=2399.0)

    def test_rejects_high_below_open(self):
        with pytest.raises(ValidationError):
            self._candle(high=2399.5)

    def test_rejects_low_above_close(self):
        with pytest.raises(ValidationError):
            self._candle(low=2401.0)

    def test_rejects_unknown_fields(self):
        with pytest.raises(ValidationError):
            self._candle(not_a_candle_field=0.618)

    def test_rejects_negative_volume(self):
        with pytest.raises(ValidationError):
            self._candle(tick_volume=-1)


class TestSymbolPropertyReading:
    def test_zero_tick_size_is_normalised_to_none(self):
        from app.mt5.symbols import read_symbol_properties

        mt5 = FakeMT5(symbols=[FakeSymbolInfo("XAUUSD", trade_tick_size=0.0)])
        properties = read_symbol_properties(mt5, "XAUUSD")
        assert properties is not None
        assert properties.tick_size is None
