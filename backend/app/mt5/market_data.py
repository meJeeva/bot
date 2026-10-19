"""Live market-data retrieval for the selected symbol.

Responsibilities
----------------
* Read ticks (bid / ask / last) and convert them into :class:`~app.schemas.market.Quote`.
* Compute spread in **price units** and in **points** using the symbol's own
  point size - never confuse the two.
* Read OHLC candles for the seven supported timeframes.
* Distinguish the latest *forming* candle from the latest *completed* candle.
* Refuse to invent prices: missing, zero or inverted ticks are reported as
  unavailable.

Broker time handling
--------------------
MetaTrader 5 timestamps are *broker server local time* expressed as seconds
since the epoch. Treating them as UTC silently shifts every bar by the server
offset (the MetaQuotes-Demo server used during development is UTC+3, a 10,800
second difference). :class:`ServerClock` therefore **measures** the offset
against the local UTC clock and caches it. The offset is only re-measured while
broker timestamps are still advancing, so a frozen feed cannot be re-anchored
to "now" and masquerade as live data.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from ..logging_config import get_logger
from ..schemas.market import Candle, Quote
from .timeframes import TimeframeSpec, get_timeframe

logger = get_logger(__name__)

TIME_CONVENTION = "broker_server_local"

# The offset is measured to the second.
#
# Rounding it to a coarse step (whole quarter hours, say) looks tidy but is
# actively wrong: it can shift a bar boundary by several minutes, which is
# enough to classify the newest *closed* M1 bar as still forming. Bar
# completion is decided by comparing a bar's open time plus its duration
# against now, so the offset must carry second-level accuracy.
_OFFSET_ROUNDING_SECONDS = 1
_MAX_ABS_OFFSET_SECONDS = 14 * 3600
# How long a measured offset is trusted before it is re-measured.
_OFFSET_REFRESH_SECONDS = 600
# Absorb integer-second jitter, but still re-anchor on a meaningful drift.
_OFFSET_DRIFT_TOLERANCE_SECONDS = 30
# A negative age larger than this means the offset is wrong, not the data.
_NEGATIVE_AGE_TOLERANCE_SECONDS = 5.0
# Best-effort delay before re-reading a historical range the terminal had not
# finished synchronising. Sleeps on the MT5 worker thread, never the event loop.
_RANGE_RETRY_DELAY_SECONDS = 0.5


class MarketDataError(RuntimeError):
    """Raised when market data cannot be retrieved from the terminal."""

    def __init__(self, code: str, message: str, detail: Any | None = None) -> None:
        self.code = code
        self.message = message
        self.detail = detail
        super().__init__(message)


def _round_offset(seconds: float) -> int:
    """Round a measured offset to whole seconds."""
    return int(round(seconds / _OFFSET_ROUNDING_SECONDS) * _OFFSET_ROUNDING_SECONDS)


@dataclass
class ServerClock:
    """Measures and caches the broker server's UTC offset.

    The offset is measured from the newest broker timestamp and only
    re-measured while that timestamp is still advancing, which prevents a
    stalled feed from being silently treated as current.
    """

    refresh_seconds: float = _OFFSET_REFRESH_SECONDS
    drift_tolerance_seconds: float = _OFFSET_DRIFT_TOLERANCE_SECONDS

    offset_seconds: int = 0
    measured_at: datetime | None = None
    last_raw_time: int | None = None
    drift_detected: bool = False

    @property
    def measured(self) -> bool:
        return self.measured_at is not None

    def observe(self, raw_broker_time: int | None, now_utc: datetime) -> int:
        """Return the current offset after optionally re-measuring it."""
        if raw_broker_time is None or raw_broker_time <= 0:
            return self.offset_seconds

        raw_broker_time = int(raw_broker_time)
        due = (
            self.measured_at is None
            or (now_utc - self.measured_at).total_seconds() >= self.refresh_seconds
        )

        if due:
            broker_wall_clock = datetime.fromtimestamp(raw_broker_time, tz=timezone.utc)
            candidate = _round_offset((broker_wall_clock - now_utc).total_seconds())

            if abs(candidate) > _MAX_ABS_OFFSET_SECONDS:
                logger.warning(
                    "Ignoring implausible server offset of %ss (raw=%s, now=%s)",
                    candidate,
                    raw_broker_time,
                    now_utc.isoformat(),
                )
            else:
                advanced = (
                    self.last_raw_time is None or raw_broker_time > self.last_raw_time
                )
                if self.measured_at is None or advanced:
                    if abs(candidate - self.offset_seconds) > self.drift_tolerance_seconds:
                        if self.measured_at is not None:
                            logger.warning(
                                "Broker server clock offset changed from %ss to %ss",
                                self.offset_seconds,
                                candidate,
                            )
                            self.drift_detected = True
                        self.offset_seconds = candidate
                    self.measured_at = now_utc
                else:
                    # Feed is not advancing: keep the previous anchor so stale
                    # data keeps looking stale instead of "refreshing" itself.
                    logger.debug(
                        "Broker feed not advancing (%s <= %s); keeping offset %ss",
                        raw_broker_time,
                        self.last_raw_time,
                        self.offset_seconds,
                    )

        self.last_raw_time = raw_broker_time
        return self.offset_seconds

    def reset(self) -> None:
        self.offset_seconds = 0
        self.measured_at = None
        self.last_raw_time = None
        self.drift_detected = False


def broker_to_broker_wall_clock(raw_epoch: int) -> datetime:
    """Broker wall-clock instant, tagged UTC purely for transport."""
    return datetime.fromtimestamp(int(raw_epoch), tz=timezone.utc)


def broker_to_utc(raw_epoch: int, offset_seconds: int) -> datetime:
    """Convert a raw broker timestamp into a true UTC instant."""
    return broker_to_broker_wall_clock(raw_epoch) - timedelta(seconds=offset_seconds)


def compute_spread(
    bid: float, ask: float, point: float
) -> tuple[float, float]:
    """Return ``(spread_price, spread_points)`` for a valid bid/ask pair.

    ``spread_points`` is the price difference divided by the symbol's point
    size - not the raw price difference.
    """
    spread_price = round(ask - bid, 10)
    if point <= 0:
        raise MarketDataError("invalid_point", f"Symbol point size must be > 0, got {point}")
    spread_points = round(spread_price / point, 6)
    return spread_price, spread_points


def _is_usable_price(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    if number != number:  # NaN
        return False
    return number > 0


def read_quote(
    mt5: Any,
    symbol: str,
    *,
    point: float,
    digits: int,
    tick_size: float | None = None,
    tick_value: float | None = None,
    stale_threshold_seconds: float,
    clock: ServerClock,
    now_utc: datetime | None = None,
) -> Quote | None:
    """Read the newest tick and build a :class:`Quote`.

    Returns ``None`` when the terminal has no usable tick for the symbol.
    Prices that are missing, zero, NaN or inverted are reported as unavailable
    rather than replaced with a guessed value.
    """
    now_utc = now_utc or datetime.now(timezone.utc)

    try:
        tick = mt5.symbol_info_tick(symbol)
    except Exception as exc:
        logger.error("symbol_info_tick(%r) raised: %s", symbol, exc)
        return None

    if tick is None:
        logger.warning(
            "No tick available for %r (last_error=%s)",
            symbol,
            _last_error_text(mt5),
        )
        return None

    raw_time = getattr(tick, "time", None)
    offset = clock.observe(raw_time, now_utc)

    bid = float(tick.bid) if _is_usable_price(getattr(tick, "bid", None)) else None
    ask = float(tick.ask) if _is_usable_price(getattr(tick, "ask", None)) else None
    # A zero "last" is normal on quote-driven feeds; report it as unavailable.
    last = float(tick.last) if _is_usable_price(getattr(tick, "last", None)) else None

    if bid is None or ask is None or ask < bid:
        logger.warning(
            "Discarding unusable tick for %r: bid=%r ask=%r",
            symbol,
            getattr(tick, "bid", None),
            getattr(tick, "ask", None),
        )
        return None

    spread_price, spread_points = compute_spread(bid, ask, point)

    tick_time_broker: datetime | None = None
    tick_time_utc: datetime | None = None
    age_seconds: float | None = None
    freshness = "unknown"
    is_stale = False

    if raw_time:
        tick_time_broker = broker_to_broker_wall_clock(raw_time)
        tick_time_utc = broker_to_utc(raw_time, offset)
        age_seconds = (now_utc - tick_time_utc).total_seconds()
        if age_seconds < -_NEGATIVE_AGE_TOLERANCE_SECONDS:
            logger.warning(
                "Negative tick age (%.1fs) for %r - measured server offset may be "
                "wrong (offset=%ss). Treating age as unknown.",
                age_seconds,
                symbol,
                offset,
            )
            age_seconds = None
            freshness = "unknown"
            is_stale = True
        else:
            age_seconds = max(0.0, age_seconds)
            is_stale = age_seconds > stale_threshold_seconds
            freshness = "stale" if is_stale else "live"
    else:
        is_stale = True

    quote = Quote(
        symbol=symbol,
        bid=bid,
        ask=ask,
        last=last,
        spread_price=spread_price,
        spread_points=spread_points,
        point=point,
        digits=digits,
        tick_size=tick_size,
        tick_value=tick_value,
        tick_time_broker=tick_time_broker,
        tick_time_utc=tick_time_utc,
        age_seconds=age_seconds,
        freshness=freshness,
        is_stale=is_stale,
        received_at=now_utc,
        server_time_offset_seconds=offset,
    )

    _warn_on_broker_spread_mismatch(mt5, symbol, spread_points)
    return quote


def _warn_on_broker_spread_mismatch(mt5: Any, symbol: str, spread_points: float) -> None:
    """Cross-check our point-based spread against the broker's own field."""
    try:
        info = mt5.symbol_info(symbol)
    except Exception:  # pragma: no cover - defensive
        return
    broker_spread = getattr(info, "spread", None) if info is not None else None
    if broker_spread is None:
        return
    if abs(float(broker_spread) - float(spread_points)) > 1.5:
        logger.debug(
            "Spread cross-check for %r differs: computed=%s points, broker=%s points",
            symbol,
            spread_points,
            broker_spread,
        )


def read_candles(
    mt5: Any,
    symbol: str,
    timeframe: str | TimeframeSpec,
    limit: int,
    *,
    offset_seconds: int,
    now_utc: datetime | None = None,
) -> list[Candle]:
    """Read ``limit`` most recent bars for ``timeframe``.

    Bars are returned oldest-first. Invalid bars are dropped with a warning
    instead of poisoning the series.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    spec = timeframe if isinstance(timeframe, TimeframeSpec) else get_timeframe(timeframe)

    if limit <= 0:
        raise MarketDataError("invalid_limit", f"Candle limit must be > 0, got {limit}")

    try:
        rates = mt5.copy_rates_from_pos(symbol, spec.mt5_value, 0, limit)
    except Exception as exc:
        raise MarketDataError(
            "mt5_call_failed",
            f"copy_rates_from_pos failed for {symbol} {spec.name}: {exc}",
        ) from exc

    if rates is None:
        raise MarketDataError(
            "no_candle_data",
            f"Terminal returned no candle data for {symbol} {spec.name} "
            f"(last_error={_last_error_text(mt5)})",
        )

    if len(rates) == 0:
        raise MarketDataError(
            "empty_candle_data",
            f"Terminal returned an empty candle series for {symbol} {spec.name}",
        )

    candles, invalid = _rates_to_candles(
        rates, symbol=symbol, spec=spec, offset_seconds=offset_seconds, now_utc=now_utc
    )

    if invalid:
        logger.warning(
            "Dropped %s invalid candle(s) for %r %s", invalid, symbol, spec.name
        )

    if not candles:
        raise MarketDataError(
            "invalid_candle_data",
            f"All {len(rates)} candle(s) for {symbol} {spec.name} failed validation.",
        )

    return candles


def _rates_to_candles(
    rates: Any,
    *,
    symbol: str,
    spec: TimeframeSpec,
    offset_seconds: int,
    now_utc: datetime,
) -> tuple[list[Candle], int]:
    """Convert a MetaTrader rates array into validated :class:`Candle` objects.

    Shared by the live (``copy_rates_from_pos``) and historical
    (``copy_rates_range``) readers so both apply identical validation, ordering
    and broker-to-UTC conversion. Returns ``(candles, invalid_count)``; the
    caller decides how to react to dropped rows.
    """
    candles: list[Candle] = []
    invalid = 0

    for rate in rates:
        try:
            raw_time = int(rate["time"])
        except Exception:  # pragma: no cover - defensive
            invalid += 1
            continue

        open_time_broker = broker_to_broker_wall_clock(raw_time)
        open_time_utc = broker_to_utc(raw_time, offset_seconds)
        is_closed = (open_time_utc + timedelta(seconds=spec.seconds)) <= now_utc

        try:
            candle = Candle(
                time=raw_time,
                open_time_broker=open_time_broker,
                open_time_utc=open_time_utc,
                open=float(rate["open"]),
                high=float(rate["high"]),
                low=float(rate["low"]),
                close=float(rate["close"]),
                tick_volume=int(rate["tick_volume"]),
                spread_points=int(rate["spread"]) if "spread" in _fields(rate) else None,
                real_volume=(
                    int(rate["real_volume"]) if "real_volume" in _fields(rate) else None
                ),
                is_closed=is_closed,
            )
        except Exception as exc:
            invalid += 1
            logger.debug(
                "Dropping invalid candle for %r %s at %s: %s",
                symbol,
                spec.name,
                raw_time,
                exc,
            )
            continue

        candles.append(candle)

    return candles, invalid


def _as_utc_epoch(value: datetime) -> int:
    """Absolute epoch seconds for a historical range bound.

    Range bounds are a UTC contract: a timezone-aware datetime is converted to
    UTC, while a naive datetime is assumed to already be UTC - *not* the
    machine's local time, which is what a bare ``.timestamp()`` would do.
    """
    if value.tzinfo is None:
        return int(value.replace(tzinfo=timezone.utc).timestamp())
    return int(value.timestamp())


def _mt5_range_datetime(bar_epoch: int) -> datetime:
    """Render a bar-time epoch as the naive datetime ``copy_rates_range`` wants.

    MetaTrader bar timestamps are broker wall-clock seconds stored as epoch
    values, while the MetaTrader5 Python API converts naive ``datetime``
    arguments with the **local machine** timezone (``mktime``). Building the
    local wall-clock rendering of the intended bar-time epoch therefore
    requests exactly that bar window, however the machine clock, the broker
    clock and their timezones relate to each other.
    """
    return datetime.fromtimestamp(bar_epoch)


def _copy_rates_range(
    mt5: Any,
    symbol: str,
    spec: TimeframeSpec,
    broker_from: datetime,
    broker_to: datetime,
) -> Any:
    try:
        return mt5.copy_rates_range(symbol, spec.mt5_value, broker_from, broker_to)
    except Exception as exc:
        raise MarketDataError(
            "mt5_call_failed",
            f"copy_rates_range failed for {symbol} {spec.name}: {exc}",
        ) from exc


def _range_coverage_gap(
    rates: Any,
    *,
    bar_from: int,
    bar_to: int,
    spec_seconds: int,
    latest_closed_bar: int,
) -> bool:
    """True when the terminal returned a range with missing edges.

    The terminal may still be downloading history it was just asked about, so
    a first read can stop short of the requested start or of the newest closed
    bar. An empty result counts as a gap.
    """
    if rates is None or len(rates) == 0:
        return True
    first = int(rates[0]["time"])
    last = int(rates[-1]["time"])
    if first > bar_from + spec_seconds:
        return True
    # The requested end may lie beyond anything that has closed yet.
    tail_limit = min(bar_to, latest_closed_bar)
    return last < tail_limit - spec_seconds


def read_candles_range(
    mt5: Any,
    symbol: str,
    timeframe: str | TimeframeSpec,
    start_utc: datetime,
    end_utc: datetime,
    *,
    offset_seconds: int,
    now_utc: datetime | None = None,
    max_candles: int | None = None,
) -> list[Candle]:
    """Read historical bars for an explicit UTC range (oldest first).

    Used by the Phase 3 historical replay. ``start_utc``/``end_utc`` are UTC
    instants (a naive datetime is assumed to be UTC) addressed in the
    terminal's broker wall-clock timeline with the same measured offset the
    live path uses. The fetch is bounded by ``max_candles`` *before* MetaTrader
    is called, retried once when the terminal returns a partially synchronised
    window, and clipped to the requested range (end exclusive). It performs
    **no** fabrication: an empty range, a failed call or an oversized range are
    reported as errors.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    spec = timeframe if isinstance(timeframe, TimeframeSpec) else get_timeframe(timeframe)

    start_epoch = _as_utc_epoch(start_utc)
    end_epoch = _as_utc_epoch(end_utc)

    if end_epoch <= start_epoch:
        raise MarketDataError(
            "invalid_range",
            "Historical end time must be after the start time.",
        )

    # Bound the request before touching MetaTrader so a wide range cannot pull
    # an unbounded history into memory. Same upper-bound estimate the replay
    # service validates, so an approved request is never rejected here.
    if max_candles is not None:
        estimated = (end_epoch - start_epoch) // spec.seconds
        if estimated > max_candles:
            raise MarketDataError(
                "range_too_large",
                f"The requested range spans about {estimated} {spec.name} bars, "
                f"which exceeds the limit of {max_candles}. Narrow the time range.",
                detail={"estimated": int(estimated), "max": int(max_candles)},
            )

    # Bar-time window: true UTC shifted into the broker wall-clock timeline.
    bar_from = start_epoch + offset_seconds
    bar_to = end_epoch + offset_seconds
    try:
        broker_from = _mt5_range_datetime(bar_from)
        broker_to = _mt5_range_datetime(bar_to)
    except (OverflowError, OSError, ValueError) as exc:
        raise MarketDataError(
            "invalid_range",
            "The requested historical range is outside the window this terminal can read.",
        ) from exc

    rates = _copy_rates_range(mt5, symbol, spec, broker_from, broker_to)

    latest_closed_bar = int(now_utc.timestamp()) + offset_seconds - spec.seconds
    if _range_coverage_gap(
        rates,
        bar_from=bar_from,
        bar_to=bar_to,
        spec_seconds=spec.seconds,
        latest_closed_bar=latest_closed_bar,
    ):
        # A first read can come back from history the terminal has not finished
        # syncing. One short, bounded retry on the worker thread usually
        # completes it; if not, the replay dataset reports the partial coverage
        # instead of this reader inventing candles.
        time.sleep(_RANGE_RETRY_DELAY_SECONDS)
        try:
            retry = _copy_rates_range(mt5, symbol, spec, broker_from, broker_to)
        except MarketDataError:
            retry = None
        if retry is not None and (rates is None or len(retry) > len(rates)):
            rates = retry

    if rates is None:
        raise MarketDataError(
            "no_candle_data",
            f"Terminal returned no candle data for {symbol} {spec.name} "
            f"(last_error={_last_error_text(mt5)})",
        )

    # Clip to the requested window; the end bound is exclusive, so a bar
    # opening exactly at ``end_utc`` is never part of the dataset.
    in_window = [rate for rate in rates if bar_from <= int(rate["time"]) < bar_to]

    if len(in_window) == 0:
        raise MarketDataError(
            "empty_candle_data",
            f"The requested range contains no {symbol} {spec.name} bars.",
        )

    if max_candles is not None and len(in_window) > max_candles:
        raise MarketDataError(
            "range_too_large",
            f"The requested range contains {len(in_window)} {symbol} {spec.name} bars, "
            f"which exceeds the limit of {max_candles}. Narrow the time range.",
            detail={"count": int(len(in_window)), "max": int(max_candles)},
        )

    candles, invalid = _rates_to_candles(
        in_window, symbol=symbol, spec=spec, offset_seconds=offset_seconds, now_utc=now_utc
    )

    if invalid:
        logger.warning(
            "Dropped %s invalid historical candle(s) for %r %s", invalid, symbol, spec.name
        )

    if not candles:
        raise MarketDataError(
            "invalid_candle_data",
            f"All {len(rates)} historical candle(s) for {symbol} {spec.name} "
            "failed validation.",
        )

    return candles


def _fields(rate: Any) -> tuple[str, ...]:
    dtype = getattr(rate, "dtype", None)
    names = getattr(dtype, "names", None)
    return tuple(names) if names else ()


def _last_error_text(mt5: Any) -> str:
    try:
        error = mt5.last_error()
    except Exception:  # pragma: no cover - defensive
        return "unknown"
    if isinstance(error, tuple) and len(error) == 2:
        return f"{error[0]}: {error[1]}"
    return str(error)


def latest_closed_candle(candles: Sequence[Candle]) -> Candle | None:
    """Newest bar that is definitely complete."""
    for candle in reversed(candles):
        if candle.is_closed:
            return candle
    return None


def forming_candle(candles: Sequence[Candle]) -> Candle | None:
    """The bar that is still forming, when one is present."""
    if candles and not candles[-1].is_closed:
        return candles[-1]
    return None
