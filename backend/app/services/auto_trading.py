"""Configured-instrument M1 stop-order strategy controller.

This is the automatic-trading engine behind the existing
``/api/auto-trading`` endpoints and the dashboard's Start/Stop controls.  It
uses the one shared :class:`~app.mt5.connection.MT5Connection` and
:class:`~app.services.market_monitor.MarketMonitor`; it never creates a second
terminal connection or a parallel engine.

Strategy, exactly as specified
------------------------------
1. **Value phase** - capture the live market price ``R`` and place two pending
   stop entries: Buy Stop at ``R + 1.00`` with SL ``R`` and Sell Stop at
   ``R - 1.00`` with SL ``R``.  No take-profit is attached to either side.
2. **Removing phase** - once one side is reached/filled, the unfilled opposite
   pending entry is removed (idempotently, never the active position's SL).
3. **Switching phase** - when the active position is *confirmed* closed by its
   stop-loss (initial or trailed), the cycle is completed and a new cycle is
   initialised from the latest live price.

Price management reacts to live ticks, not candle closes.  A position is never
closed because a one-minute candle ended.

State is persisted to the existing SQLite store when available and always
reconciled against real MT5 positions, pending orders and deals before orders
are submitted.
"""

from __future__ import annotations

import asyncio
import math
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import Settings
from ..logging_config import get_logger
from ..mt5.connection import MT5Connection, describe_mt5_error
from ..mt5.market_data import compute_spread
from ..schemas.auto_trading import (
    AutoTradingHistoryItem,
    AutoTradingHistoryResponse,
    AutoTradingStatus,
)
from ..services.market_monitor import MarketMonitor
from ..strategy.range_break_even import (
    PRICE_OFFSET,
    STRATEGY_SYMBOL,
    STRATEGY_TIMEFRAME,
    build_cycle_levels,
    buy_activation_price,
    calculate_atr,
    effective_trailing_distance,
    next_buy_stop_loss,
    next_sell_stop_loss,
    normalize_price,
    price_tolerance,
    sell_activation_price,
)
from ..mt5.timeframes import get_timeframe
from ..strategy.range_break_even import (
    CycleLevels as _CycleLevels,
)

logger = get_logger(__name__)

# Scheduler granularity. The market monitor publishes ticks; the strategy loop
# only has to observe them promptly.
_WAIT_SLICE_SECONDS = 0.1
_CONFIRM_POLL_SECONDS = 0.1
_CONFIRM_TIMEOUT_SECONDS = 5.0
_CLOSED_CONFIRM_TIMEOUT_SECONDS = 8.0
_ORDER_RETRY_SECONDS = 2.0
_SL_RETRY_SECONDS = 1.0
_PERSIST_MIN_INTERVAL_SECONDS = 1.0
_HISTORY_LOOKBACK_DAYS = 7

# MT5 constants, with defensive fallbacks so the fake/older packages work.
_DEAL_ENTRY_OUT = 1
_DEAL_REASON_SL = 4

# Detailed state-machine phases (published in the status payload).
PHASE_STOPPED = "STOPPED"
PHASE_INITIALIZING = "INITIALIZING"
PHASE_WAITING_ENTRY = "WAITING_ENTRY"
PHASE_BUY_OPEN = "BUY_OPEN"
PHASE_SELL_OPEN = "SELL_OPEN"
PHASE_SWITCHING = "SWITCHING"
# The strategy is healthy but is withholding entries because the live spread
# exceeds the configured maximum. This is not an execution failure: the loop
# keeps running and arms the cycle as soon as the spread returns within range.
PHASE_SPREAD_BLOCKED = "SPREAD_BLOCKED"
PHASE_ERROR = "ERROR"

SIDE_BUY = "buy"
SIDE_SELL = "sell"

SPREAD_OK = "ok"
SPREAD_BLOCKED = "blocked"
SPREAD_UNAVAILABLE = "unavailable"

# Pending stop-order validation outcomes. They are decided *before* anything
# reaches the broker, from a freshly-read tick, so an invalid request is never
# submitted in the first place.
ENTRY_VALID = "valid"
ENTRY_CROSSED = "crossed"  # the market already traded through the level
ENTRY_STOPS = "stops"      # broker minimum stop distance not satisfied
ENTRY_SL_SIDE = "sl_side"  # protective stop on the wrong side of the entry

# Broker rejections that mean "the market is no longer on the right side of
# this request": TRADE_RETCODE_INVALID_PRICE (10015). Only this code may be
# rebuilt from a fresh tick; every other rejection keeps the existing
# backoff-and-report policy so an identical invalid request is never resent.
_PRICE_REJECTED_RETCODES = frozenset({10015})

# Slack for price comparisons. Bid/Ask and the requested price come from two
# independent reads; without it float noise alone would look like a crossed
# level. It is many orders of magnitude below one tick.
_SLACK = 1e-9


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_comment(prefix: str, counter: int) -> str:
    """Generate a valid MT5 order comment (31 characters maximum)."""
    comment = f"{prefix}{counter}"
    return comment[:31]


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(obj, name)
    except Exception:  # noqa: BLE001 - third-party result objects
        return default


def _format_number(value: float | None) -> str:
    if value is None:
        return "unavailable"
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def _format_price(value: float | None) -> str:
    """Prices keep their reported precision (no 6-significant-digit cut)."""
    if value is None:
        return "unavailable"
    try:
        return repr(float(value))
    except (TypeError, ValueError):
        return str(value)


@dataclass(frozen=True)
class SpreadCheck:
    """One spread measurement together with the limit it was compared with.

    ``spread_points`` is always ``(ask - bid) / SYMBOL_POINT`` - the same unit
    as ``auto_trade_max_spread_points`` - never the raw price difference, so a
    price difference can never be compared with a points-based limit.
    """

    outcome: str
    symbol: str | None
    profile: str | None
    limit: float | None
    bid: float | None = None
    ask: float | None = None
    spread_price: float | None = None
    spread_points: float | None = None
    point: float | None = None
    digits: int | None = None
    detail: str | None = None

    @property
    def blocked(self) -> bool:
        return self.outcome == SPREAD_BLOCKED

    @property
    def unavailable(self) -> bool:
        return self.outcome == SPREAD_UNAVAILABLE

    def describe(self) -> str:
        """Every measured value on one line (no credentials involved)."""
        if self.unavailable:
            return (
                f"spread unavailable ({self.detail}) | symbol={self.symbol} "
                f"profile={self.profile} bid={_format_price(self.bid)} "
                f"ask={_format_price(self.ask)} "
                f"SYMBOL_POINT={self.point} digits={self.digits} "
                f"max={_format_number(self.limit)} points"
            )
        return (
            f"spread={_format_number(self.spread_points)} points "
            f"({_format_price(self.spread_price)} price units) | "
            f"max={_format_number(self.limit)} points | "
            f"symbol={self.symbol} profile={self.profile} "
            f"bid={_format_price(self.bid)} ask={_format_price(self.ask)} "
            f"SYMBOL_POINT={self.point} digits={self.digits} | "
            f"blocked={'yes' if self.blocked else 'no'}"
        )

    def reason(self) -> str:
        """The precise message reported through ``last_error``."""
        if self.unavailable:
            return f"Spread cannot be verified: {self.detail}"
        if self.blocked:
            # Bid/ask are deliberately left out of the reported reason: they
            # change on every tick, and the full values stay in the log line
            # produced by `describe()`.
            return (
                "Spread exceeds maximum: "
                f"{_format_number(self.spread_points)} points > "
                f"{_format_number(self.limit)} configured "
                f"(symbol={self.symbol}, profile={self.profile}, "
                f"spread={_format_number(self.spread_price)} price units, "
                f"point={self.point}, digits={self.digits})"
            )
        return (
            "Spread within maximum: "
            f"{_format_number(self.spread_points)} points <= "
            f"{_format_number(self.limit)} configured"
        )


@dataclass(frozen=True)
class StopOrderCheck:
    """The result of validating one pending stop request against a live tick."""

    outcome: str
    reason: str | None = None
    #: Distance from the market to the requested price (sign depends on side).
    gap: float | None = None
    #: Broker minimum distance required, in price units (`stops_level` points).
    required_gap: float | None = None
    #: True only when the market already carried the intended level away.
    crossed: bool = False

    @property
    def ok(self) -> bool:
        return self.outcome == ENTRY_VALID


@dataclass(frozen=True)
class StopMoveValidation:
    """The result of validating one SLTP modification against a fresh tick.

    ``ok`` means the request may be submitted using the tick observed right
    here. ``reason`` names the exact current condition that blocks the
    request; the caller defers instead of submitting and preserves the
    broker's existing stop.
    """

    position: Any | None = None
    bid: float | None = None
    ask: float | None = None
    tick_time: Any = None
    stops_points: int = 0
    freeze_points: int = 0
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.position is not None and self.reason is None


def check_stop_order(
    side: str,
    price: float,
    sl: float | None,
    bid: float,
    ask: float,
    *,
    point: float | None = None,
    stops_level: int | None = None,
) -> StopOrderCheck:
    """Validate a pending stop order against a *fresh* market tick.

    A Sell Stop is only accepted while its price is at or below the current
    Bid, a Buy Stop only while it is at or above the current Ask. Once the
    market trades through the level the broker rejects the request with
    ``10015 Invalid price``, which is exactly what an aggressive XAUUSD move
    produces when a stop is submitted from a cached quote.

    ``stops_level`` (``SYMBOL_TRADE_STOPS_LEVEL``) is the broker's minimum
    distance in points between the current price and a new pending order; it
    is converted to price units with ``SYMBOL_POINT``.
    """
    required = 0.0
    try:
        if (
            stops_level is not None
            and point is not None
            and float(stops_level) > 0
            and float(point) > 0
        ):
            required = float(stops_level) * float(point)
    except (TypeError, ValueError):
        required = 0.0

    if side == SIDE_SELL:
        # Positive while the entry still waits below the Bid.
        gap = float(bid) - float(price)
        sl_gap = None if sl is None else float(sl) - float(price)
        market_word, sl_word = "above the current Bid", "below the Sell entry"
    else:
        # Positive while the entry still waits above the Ask.
        gap = float(price) - float(ask)
        sl_gap = None if sl is None else float(price) - float(sl)
        market_word, sl_word = "below the current Ask", "above the Buy entry"

    if gap < -_SLACK:
        return StopOrderCheck(
            ENTRY_CROSSED,
            reason=(
                f"the market already traded through the intended {side} entry "
                f"(gap={gap:g} price units, bid={bid:g} ask={ask:g})"
            ),
            gap=gap,
            required_gap=required,
            crossed=True,
        )
    if gap + _SLACK < required:
        return StopOrderCheck(
            ENTRY_STOPS,
            reason=(
                f"the requested price is only {gap:g} price units {market_word} "
                f"but the broker requires {required:g} "
                f"(stops_level={stops_level} point={point})"
            ),
            gap=gap,
            required_gap=required,
        )
    if sl_gap is not None:
        if sl_gap < -_SLACK:
            return StopOrderCheck(
                ENTRY_SL_SIDE,
                reason=(
                    f"the initial stop is {sl_gap:g} price units {sl_word} "
                    f"(entry={price:g} sl={sl:g})"
                ),
                gap=sl_gap,
                required_gap=required,
            )
        if sl_gap + _SLACK < required:
            return StopOrderCheck(
                ENTRY_STOPS,
                reason=(
                    f"the initial stop is only {sl_gap:g} price units from the "
                    f"entry but the broker requires {required:g} "
                    f"(stops_level={stops_level} point={point})"
                ),
                gap=sl_gap,
                required_gap=required,
            )
    return StopOrderCheck(
        ENTRY_VALID, gap=gap, required_gap=required, crossed=False
    )


def _price_rejected(retcode: Any) -> bool:
    """Whether ``retcode`` says the price is no longer on the valid side.

    ``TRADE_RETCODE_INVALID_PRICE`` (10015) is the only code that a moved
    market explains; ``10016 invalid stops`` is a hard rejection that is
    reported and backed off, never resent.
    """
    try:
        return int(retcode) in _PRICE_REJECTED_RETCODES
    except (TypeError, ValueError):
        return False


def _is_strategy_symbol(symbol: str | None, base: str | None) -> bool:
    """Whether ``symbol`` is a broker variant of the configured instrument.

    Broker suffixes and prefixes are accepted (``XAUUSDm``, ``XAUUSD.c``,
    ``#XAUUSD``) but a *different* instrument never is. There is no fallback
    to another symbol: if the configured instrument cannot be resolved, the
    deployment stays blocked.
    """
    if not symbol or not base:
        return False
    try:
        from ..mt5.symbols import classify_symbol_variant

        return classify_symbol_variant(str(symbol), str(base)) is not None
    except Exception:  # noqa: BLE001 - defensive fallback
        normalised = str(symbol).strip().upper().replace("#", "").replace("/", "")
        return normalised.startswith(str(base).strip().upper())


class AutoTradingController:
    """State machine for the M1 value/removing/switching strategy.

    The instrument (default XAUUSD) and its distances come from settings; the
    three-phase lifecycle itself is instrument-independent.
    """

    def __init__(
        self,
        settings: Settings,
        connection: MT5Connection,
        monitor: MarketMonitor,
        store: Any = None,
    ) -> None:
        self.settings = settings
        self.connection = connection
        self.monitor = monitor
        self.store = store

        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._stop_requested = False
        self._stop_event = asyncio.Event()

        # Lifecycle / session
        self._status = "STOPPED"
        self._phase = PHASE_STOPPED
        self._session_id: str | None = None
        self._cycle_counter = 0
        self._current_cycle_id: str | None = None
        self._start_balance: float | None = None

        # Cycle levels
        self._reference_value: float | None = None
        self._buy_entry: float | None = None
        self._buy_sl: float | None = None
        self._sell_entry: float | None = None
        self._sell_sl: float | None = None

        # Pending entry orders
        self._buy_order_ticket: int | None = None
        self._sell_order_ticket: int | None = None
        self._orders: dict[int, Any] = {}
        self._side_removed = {SIDE_BUY: False, SIDE_SELL: False}
        self._orders_missing_since: float | None = None
        self._order_retry_at = {SIDE_BUY: 0.0, SIDE_SELL: 0.0}
        self._missed_entry_since: float | None = None

        # Active position and protective stop
        self._active_side: str | None = None
        self._position_ticket: int | None = None
        self._position_type: int | None = None
        self._position: Any = None
        self._entry_price: float | None = None
        self._entry_time: datetime | None = None
        self._entry_volume: float | None = None
        self._current_profit: float | None = None
        self._current_sl: float | None = None
        self._entry_counted = False
        self._closed_since: float | None = None

        # Break-even trailing state
        self._high_water: float | None = None
        self._low_water: float | None = None
        self._break_even_active = False
        self._break_even_level: float | None = None
        self._last_sl_request_level: float | None = None
        self._sl_retry_at = 0.0
        self._sl_request_in_flight = False
        self._pending_sl_target: float | None = None

        # Dynamic trailing configuration
        # XAUUSD is the only supported instrument; its trailing-mode settings
        # are the only ones that exist.
        self._trailing_mode = str(
            getattr(settings, "xauusd_trailing_mode", None) or "static"
        ).strip().lower()
        self._trail_atr_period = int(
            getattr(settings, "xauusd_trail_atr_period", None) or 14
        )
        self._trail_atr_multiplier = float(
            getattr(settings, "xauusd_trail_atr_multiplier", None) or 0.4
        )
        self._last_trail_atr: float | None = None

        # Execution identity / deduplication
        self._last_processed_deal: Any = None
        self._previous_cycle_complete = True

        # Statistics and reporting
        self._completed_cycles = 0
        self._session_completed_cycles = 0
        self._successful_entries = 0
        self._failed_entries = 0
        self._failed_exits = 0
        self._last_entry_result: str | None = None
        self._last_exit_result: str | None = None
        self._last_error: str | None = None
        self._next_cycle: datetime | None = None
        self._history: list[AutoTradingHistoryItem] = []

        # Symbol metadata used to normalise submitted prices.
        self._tick_size: float | None = None
        self._digits: int | None = None
        # Cached broker symbol metadata and resolved symbol name. The broker
        # contract for a resolved symbol is stable for the lifetime of a
        # session, so repeated MT5 round-trips are avoided while still
        # invalidating when the resolved name changes.
        self._symbol_info_cache: Any = None
        self._symbol_info_cache_name: str | None = None
        self._resolved_symbol_cache_key: tuple[Any, Any] | None = None
        self._resolved_symbol_cached: str | None = None
        # Configured instrument identity. The strategy formulas are generic;
        # the symbol, timeframe and entry offset come from configuration, and
        # the XAUUSD module defaults apply only while nothing else is set.
        self._strategy_symbol = str(
            getattr(settings, "auto_trade_symbol", None)
            or getattr(settings, "mt5_symbol", None)
            or STRATEGY_SYMBOL
        ).upper()
        self._strategy_timeframe = str(
            getattr(settings, "auto_trade_timeframe", None) or STRATEGY_TIMEFRAME
        ).upper()
        raw_entry_offset = getattr(settings, "auto_trade_entry_offset", None)
        self._entry_offset = (
            float(raw_entry_offset) if raw_entry_offset is not None else PRICE_OFFSET
        )
        # Side-specific distances. The config validator resolves them to the
        # symmetric entry offset when the profile does not configure them, so
        # deployments without these settings behave exactly as before.
        raw_buy_offset = getattr(settings, "auto_trade_buy_entry_offset", None)
        self._buy_entry_offset = (
            float(raw_buy_offset) if raw_buy_offset is not None else self._entry_offset
        )
        raw_sell_offset = getattr(settings, "auto_trade_sell_entry_offset", None)
        self._sell_entry_offset = (
            float(raw_sell_offset) if raw_sell_offset is not None else self._entry_offset
        )
        raw_sl_distance = getattr(settings, "auto_trade_initial_sl_distance", None)
        self._initial_sl_distance = (
            float(raw_sl_distance) if raw_sl_distance is not None else self._entry_offset
        )

        # Configured strategy distances (absolute price units of the configured
        # instrument).
        self._break_even_offset = float(
            getattr(settings, "auto_trade_break_even_offset", 0.40)
        )
        self._trailing_distance = float(
            getattr(settings, "auto_trade_trailing_distance", 0.40)
        )

        self._last_persist_at = 0.0
        self._last_connectivity_log: str | None = None

        # Spread gate. The measured spread decides whether a new entry may be
        # armed; it never changes the strategy distances or the risk controls.
        self._spread_blocked = False
        self._last_spread_check: SpreadCheck | None = None
        self._spread_log_state: str | None = None
        self._phase_before_spread_block: str | None = None

        # Worker heartbeat and MT5 query tracking for status reporting.
        self._heartbeat_at: float | None = None
        self._mt5_query_ok: bool = True
        self._mt5_query_error: str | None = None
        self._pending_order_count: int = 0
        self._open_position_count: int = 0
        self._last_order_attempt: str | None = None
        self._last_broker_result: str | None = None
        self._degraded: bool = False
        self._rejected_sl_level: float | None = None
        self._worker_state: str = "STOPPED"

        # High-resolution profiling (opt-in via AUTO_TRADE_PROFILE_TIMING).
        self._profiling_enabled = bool(
            getattr(settings, "auto_trade_profile_timing", False)
        )
        self._profile_intent_seq = 0
    # ------------------------------------------------------------------
    # Small utilities
    # ------------------------------------------------------------------
    def _now(self) -> float:
        return time.monotonic()

    async def _sleep(self, seconds: float) -> None:
        await asyncio.sleep(max(0.0, seconds))

    def _profiling(self) -> bool:
        return bool(self._profiling_enabled)

    def _next_intent_id(self, side: str, attempt: int | None = None) -> str:
        self._profile_intent_seq += 1
        return f"{self._current_cycle_id or 'cycle'}:{side}:{self._profile_intent_seq if attempt is None else attempt}"

    def _profile_stage(
        self,
        stage: str,
        start_ns: int,
        *,
        side: str | None = None,
        intent_id: str | None = None,
        extra: str | None = None,
    ) -> None:
        if not self._profiling_enabled:
            return
        elapsed_us = (time.perf_counter_ns() - start_ns) / 1000.0
        logger.debug(
            "PROFILE cycle=%s intent=%s side=%s stage=%s elapsed_us=%.1f ts=%s%s",
            self._current_cycle_id,
            intent_id,
            side,
            stage,
            elapsed_us,
            _utcnow().isoformat(),
            ("" if extra is None else " " + extra),
        )
    def _poll_seconds(self) -> float:
        try:
            configured = int(getattr(self.settings, "auto_trade_poll_interval_ms", 200))
        except Exception:  # noqa: BLE001 - defensive
            configured = 200
        return max(0.05, configured / 1000.0)

    def _resolved_symbol(self) -> str | None:
        status = self.monitor.symbol_status
        resolved = getattr(status, "resolved", None) or getattr(status, "requested", None)
        # Cache the resolved name per monitor status object so the hot path
        # does not re-read monitor state on every call; invalidate when the
        # status object or its resolved value changes.
        key = (id(status), resolved)
        if self._resolved_symbol_cache_key == key:
            return self._resolved_symbol_cached
        self._resolved_symbol_cache_key = key
        self._resolved_symbol_cached = resolved
        return resolved

    def _norm(self, price: float | None) -> float | None:
        return normalize_price(price, self._tick_size, self._digits)

    def _tolerance(self) -> float:
        return price_tolerance(self._tick_size, self._digits)

    async def _get_cached_symbol_info(self, mt5: Any, symbol: str | None) -> Any:
        """Return broker metadata for ``symbol``, reusing a valid cached copy.

        The contract metadata for a resolved symbol is stable for the lifetime
        of a session, so repeated ``symbol_info`` round-trips are avoided.
        The cache invalidates automatically when the resolved symbol changes
        or when a previous read returned nothing usable.
        """
        if symbol is not None and self._symbol_info_cache is not None and self._symbol_info_cache_name == symbol:
            return self._symbol_info_cache
        info = await self.connection.acall(mt5.symbol_info, symbol)
        if info is not None and symbol is not None:
            self._symbol_info_cache = info
            self._symbol_info_cache_name = symbol
        elif symbol is None:
            self._symbol_info_cache = None
            self._symbol_info_cache_name = None
        return info

    def _adopt_price_metadata(self, info: Any) -> None:
        """Refresh the price granularity from a freshly-read ``symbol_info``.

        Prices are normalised against ``SYMBOL_TRADE_TICK_SIZE`` (falling back
        to ``SYMBOL_POINT``), never against the decimal count alone. The
        broker is re-read on every attempt so the metadata used to build a
        request can never be older than the request itself.
        """
        raw_tick = _get_attr(info, "trade_tick_size", None)
        if raw_tick is None:
            raw_tick = _get_attr(info, "point", None)
        raw_digits = _get_attr(info, "digits", None)
        try:
            if raw_tick is not None and float(raw_tick) > 0:
                self._tick_size = float(raw_tick)
        except (TypeError, ValueError):
            pass
        try:
            if raw_digits is not None and int(raw_digits) >= 0:
                self._digits = int(raw_digits)
        except (TypeError, ValueError):
            pass

    async def _read_live_tick(self) -> Any | None:
        """A brand-new broker tick, read immediately before an order is checked.

        The monitor's cached quote is never the last word on the current Bid
        and Ask: during an aggressive move it is exactly what turns a valid
        stop into ``10015 Invalid price``. ``None`` means the terminal did not
        report a usable tick, so the caller must fall back and say so.
        """
        mt5 = self.connection.mt5
        getter = getattr(mt5, "symbol_info_tick", None)
        symbol = self._resolved_symbol()
        if getter is None or not symbol:
            return None
        try:
            tick = await self.connection.acall(getter, symbol)
        except Exception:  # noqa: BLE001 - fall back, never send blind
            return None
        if tick is None:
            return None
        bid, ask = self._market_bid_ask(tick)
        if bid is None or ask is None or ask < bid:
            return None
        return tick

    @staticmethod
    def _market_bid_ask(market: Any) -> tuple[float | None, float | None]:
        """Numeric Bid/Ask from a tick or a monitor quote, or ``(None, None)``."""
        bid = _get_attr(market, "bid", None)
        ask = _get_attr(market, "ask", None)
        try:
            bid_value = float(bid)
            ask_value = float(ask)
        except (TypeError, ValueError):
            return None, None
        if not math.isfinite(bid_value) or not math.isfinite(ask_value):
            return None, None
        if bid_value <= 0 or ask_value <= 0:
            return None, None
        return bid_value, ask_value

    async def _reconcile_entry(self, side: str) -> bool:
        """Re-read MT5 and adopt an entry that already exists for ``side``.

        Called after any rejection so a delayed broker response can never
        produce a duplicate order.
        """
        logger.info(
            "RECONCILE_ENTRY cycle=%s side=%s phase=%s buy_ticket=%s sell_ticket=%s active_side=%s position=%s",
            self._current_cycle_id,
            side.upper(),
            self._phase,
            self._buy_order_ticket,
            self._sell_order_ticket,
            self._active_side,
            self._position_ticket,
        )
        await self._refresh_mt5_state()
        for order in list(self._orders.values()):
            if self._side_for_order(order) != side:
                continue
            adopted = _get_attr(order, "ticket", None)
            if adopted is None:
                continue
            if side == SIDE_BUY:
                self._buy_order_ticket = int(adopted)
            else:
                self._sell_order_ticket = int(adopted)
            logger.info(
                "ENTRY_CONFIRMED %s Stop ticket=%s adopted while reconciling a rejection",
                side.upper(),
                adopted,
            )
            return True
        return False

    async def _record_entry_missed(self, side: str, price: float, detail: str) -> None:
        """Record that the market carried the intended entry level away.

        The entry is never moved to a new price, never widened into a market
        order and the spread limit is never relaxed: the cycle keeps its own
        reference and levels, and the existing retry/cycle policy decides what
        happens next.
        """
        message = f"ENTRY_MISSED {side.upper()}: {detail}"
        logger.warning("%s", message)
        if message != self._last_entry_result:
            self._last_entry_result = message
        self._failed_entries += 1
        self._order_retry_at[side] = self._now() + _ORDER_RETRY_SECONDS
        await self._record_trade_event("entry_missed", price=price, details=detail)

    # ------------------------------------------------------------------
    # Spread gate
    # ------------------------------------------------------------------
    def _measure_spread(self, quote: Any) -> SpreadCheck:
        """Measure the live spread in points and compare it with the limit.

        Missing quotes and invalid spread inputs are reported as
        ``unavailable`` - they are never mistaken for a genuine high spread.
        """
        symbol = self._resolved_symbol() or self._strategy_symbol
        profile = getattr(self.settings, "auto_trade_profile", None)
        limit = getattr(self.settings, "auto_trade_max_spread_points", None)

        def unavailable(detail: str) -> SpreadCheck:
            try:
                limit_value = float(limit) if limit is not None else None
            except (TypeError, ValueError):
                limit_value = None
            return SpreadCheck(
                outcome=SPREAD_UNAVAILABLE,
                symbol=symbol,
                profile=profile,
                limit=limit_value,
                detail=detail,
            )

        if quote is None:
            return unavailable("no quote is available")

        bid = _get_attr(quote, "bid", None)
        ask = _get_attr(quote, "ask", None)
        if bid is None or ask is None:
            return unavailable(f"bid/ask are incomplete (bid={bid!r}, ask={ask!r})")
        try:
            bid_value = float(bid)
            ask_value = float(ask)
        except (TypeError, ValueError):
            return unavailable(f"bid/ask are not numeric (bid={bid!r}, ask={ask!r})")
        if bid_value <= 0 or ask_value <= 0:
            return unavailable(f"bid/ask are not positive (bid={bid!r}, ask={ask!r})")
        if ask_value < bid_value:
            return unavailable(f"ask is below bid (bid={bid!r}, ask={ask!r})")

        point = _get_attr(quote, "point", None)
        if point is None:
            point = self._tick_size or _get_attr(quote, "tick_size", None)
        try:
            point_value = float(point) if point is not None else None
        except (TypeError, ValueError):
            point_value = None
        if (
            point_value is None
            or not math.isfinite(point_value)
            or point_value <= 0
        ):
            return unavailable(f"symbol point size is invalid (SYMBOL_POINT={point!r})")

        try:
            spread_price, spread_points = compute_spread(
                bid_value, ask_value, point_value
            )
        except Exception as exc:  # noqa: BLE001 - reported, never guessed
            return unavailable(f"spread could not be computed: {exc}")
        if not math.isfinite(spread_points) or spread_points < 0:
            return unavailable(f"calculated spread is invalid ({spread_points!r} points)")

        digits = _get_attr(quote, "digits", None)
        if digits is None:
            digits = self._digits

        # Cross-check the quote's own figure. A mismatch means one of the two
        # sides used a different unit; the recomputed points are authoritative.
        reported = _get_attr(quote, "spread_points", None)
        if reported is not None:
            try:
                if abs(float(reported) - spread_points) > max(1.0, spread_points * 1e-6):
                    logger.warning(
                        "Spread unit mismatch for %s: quote reports %s points but "
                        "(ask-bid)/SYMBOL_POINT gives %s points (point=%s); "
                        "using the recomputed value",
                        symbol,
                        reported,
                        spread_points,
                        point_value,
                    )
            except (TypeError, ValueError):
                pass

        if limit is None:
            return unavailable("the configured maximum spread is unavailable")
        try:
            limit_value = float(limit)
        except (TypeError, ValueError):
            return unavailable(f"the configured maximum spread is invalid ({limit!r})")
        if not math.isfinite(limit_value) or limit_value < 0:
            return unavailable(
                f"the configured maximum spread is invalid ({limit!r})"
            )

        return SpreadCheck(
            outcome=SPREAD_BLOCKED if spread_points > limit_value else SPREAD_OK,
            symbol=symbol,
            profile=profile,
            limit=limit_value,
            bid=bid_value,
            ask=ask_value,
            spread_price=spread_price,
            spread_points=spread_points,
            point=point_value,
            digits=int(digits) if digits is not None else None,
        )

    def _evaluate_spread(self, quote: Any, *, context: str) -> SpreadCheck:
        """Measure the spread and log the full comparison when it changes."""
        check = self._measure_spread(quote)
        self._last_spread_check = check
        self._spread_blocked = check.blocked
        if check.outcome != self._spread_log_state:
            if check.blocked:
                logger.warning(
                    "Spread gate withheld entry (%s): %s", context, check.describe()
                )
            elif check.unavailable:
                logger.warning(
                    "Spread gate cannot verify the spread (%s): %s",
                    context,
                    check.describe(),
                )
            else:
                logger.info(
                    "Spread gate allows entry (%s): %s", context, check.describe()
                )
            self._spread_log_state = check.outcome
        else:
            logger.debug("Spread gate (%s): %s", context, check.describe())
        return check

    async def _gate_cycle_entry(self, quote: Any) -> bool:
        """Whether the spread gate currently prevents arming a new cycle.

        Returns ``True`` when the caller must skip cycle initialisation for this
        step. A resumed gate leaves the phase ready for the normal flow in the
        same step, so no cycle reference is reset and nothing is duplicated.
        """
        if self._active_side is not None:
            return False
        spread = self._evaluate_spread(quote, context="entry arming")
        if self._phase not in (
            PHASE_INITIALIZING,
            PHASE_SWITCHING,
            PHASE_SPREAD_BLOCKED,
        ):
            return False
        if spread.unavailable:
            self._note_error(spread.reason())
            return True
        if spread.blocked:
            await self._block_initialisation(spread)
            return True
        if self._phase == PHASE_SPREAD_BLOCKED:
            self._resume_from_spread_block(spread)
        return False

    async def _block_initialisation(self, check: SpreadCheck) -> None:
        """Hold a new cycle without creating (or resetting) a cycle reference."""
        if self._phase == PHASE_SPREAD_BLOCKED:
            # Already blocked: refresh the reported measurement without logging
            # a new error on every tick. `_evaluate_spread` owns the logging.
            self._last_error = check.reason()
            return
        self._note_error(check.reason())
        self._phase_before_spread_block = self._phase
        self._phase = PHASE_SPREAD_BLOCKED
        logger.warning(
            "Entry withheld until the spread returns within the configured "
            "maximum (phase before block: %s): %s",
            self._phase_before_spread_block,
            check.describe(),
        )
        await self._persist_state(force=True)

    def _resume_from_spread_block(self, check: SpreadCheck) -> None:
        previous = self._phase_before_spread_block
        self._phase_before_spread_block = None
        self._phase = (
            previous
            if previous and previous != PHASE_SPREAD_BLOCKED
            else PHASE_INITIALIZING
        )
        self._clear_spread_error()
        logger.info(
            "Spread returned within the configured maximum; resuming %s: %s",
            self._phase,
            check.describe(),
        )

    def _note_error(self, message: str) -> None:
        """Record an error, logging only when the message changes."""
        if message != self._last_error:
            logger.error("%s", message)
        self._last_error = message
        self._degraded = True

    def _compute_reported_status(self) -> str:
        if self._worker_state == "FAILED":
            return "FAILED"
        if self._worker_state in ("STOPPED",):
            return "STOPPED"
        if self._phase == PHASE_SPREAD_BLOCKED or self._spread_blocked:
            return "SPREAD_BLOCKED"
        if getattr(self.settings, "auto_trade_read_only", False):
            return "READ_ONLY"
        if self._degraded or self._mt5_query_error is not None:
            if not (self._phase == PHASE_SPREAD_BLOCKED or self._spread_blocked):
                return "DEGRADED"
        if self._phase == PHASE_WAITING_ENTRY and self._active_side is None and self._position_ticket is None:
            return "WAITING"
        return "RUNNING"

    def _fail(self, message: str) -> None:
        self._note_error(message)
        self._worker_state = "FAILED"
        self._status = "FAILED"
        self._phase = PHASE_ERROR
        self._stop_requested = True
        self._degraded = False

    def _clear_spread_error(self) -> None:
        """Drop only the spread-blocked message once the spread is acceptable."""
        if self._last_error and self._last_error.startswith("Spread exceeds maximum"):
            self._last_error = None
            self._degraded = False

    async def _record_trade(self, trade: dict[str, Any]) -> None:
        store = self.store
        if store is None:
            return
        _db_start_ns = time.perf_counter_ns()
        try:
            await asyncio.to_thread(store.record_trade, trade)
        except Exception as exc:  # noqa: BLE001 - persistence must not break execution
            logger.warning("Trade record failed: %s", exc)
        self._profile_stage("db_trade_record", _db_start_ns, extra=f"event={trade.get('status')}")

    async def _record_trade_event(self, event_type: str, **kwargs: Any) -> None:
        store = self.store
        if store is None:
            return
        trade_id = kwargs.get("trade_id")
        event_id = f"{self._current_cycle_id or 'cycle'}:{event_type}:{self._position_ticket or kwargs.get('ticket') or 0}"
        payload = {
            "event_id": event_id,
            "cycle_id": self._current_cycle_id,
            "trade_id": trade_id,
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "broker_timestamp": kwargs.get("broker_timestamp"),
            "price": kwargs.get("price"),
            "order_ticket": kwargs.get("order_ticket"),
            "position_id": kwargs.get("position_id"),
            "result_code": kwargs.get("result_code"),
            "details": kwargs.get("details"),
        }
        try:
            await asyncio.to_thread(store.record_trade_event, payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Trade event record failed: %s", exc)

    def _filling_mode(self, mt5: Any, info: Any) -> int:
        filling_mode = _get_attr(info, "filling_mode", None)
        ioc = _get_attr(mt5, "ORDER_FILLING_IOC", 1)
        fok = _get_attr(mt5, "ORDER_FILLING_FOK", 0)
        if filling_mode is not None:
            if filling_mode & 2:
                return ioc
            if filling_mode & 1:
                return fok
        return fok

    def _stop_closes_position(self) -> bool:
        policy = str(self.settings.auto_trade_stop_policy or "close").strip().lower()
        return policy != "leave"

    # ------------------------------------------------------------------
    # Start / stop
    # ------------------------------------------------------------------
    async def start(self):
        async with self._lock:
            if self._task is not None and not self._task.done():
                # A second Start must never launch a second trading loop.
                return await self._build_status_unlocked()

            self._stop_requested = False
            self._stop_event.clear()
            self._worker_state = "STARTING"
            self._status = "RUNNING"
            self._phase = PHASE_INITIALIZING
            self._last_error = None
            self._degraded = False
            self._heartbeat_at = self._now()
            # Each session measures (and logs) the spread from scratch.
            self._spread_blocked = False
            self._last_spread_check = None
            self._spread_log_state = None
            self._phase_before_spread_block = None
            self._session_completed_cycles = 0
            self._session_id = str(uuid.uuid4())
            self._closed_since = None

            try:
                await self._preflight()
                await self._restore_state_unlocked()
            except Exception as exc:  # noqa: BLE001 - report, do not trade
                self._worker_state = "FAILED"
                self._status = "FAILED"
                self._phase = PHASE_ERROR
                self._last_error = str(exc)
                logger.error("Auto-trading preflight failed: %s", exc)
                return await self._build_status_unlocked()

            # Report the spread-blocked state straight away instead of waiting
            # for the first scheduler tick; the loop re-checks it every step.
            quote = self.monitor.latest_quote()
            if quote is not None and not _get_attr(quote, "is_stale", False):
                await self._gate_cycle_entry(quote)

            self._start_balance = await self._account_balance()
            self._worker_state = "RUNNING"
            self._status = "RUNNING"
            self._task = asyncio.create_task(self._run(), name="auto-trading")
            logger.info(
                "Strategy started (session=%s, symbol=%s, timeframe=%s, "
                "break_even_offset=%s, trailing_distance=%s, lot_size=%s, "
                "stop_policy=%s)",
                self._session_id,
                self._resolved_symbol(),
                STRATEGY_TIMEFRAME,
                self._break_even_offset,
                self._trailing_distance,
                self.settings.auto_trade_lot_size,
                self.settings.auto_trade_stop_policy,
            )

        return await self.status()

    async def stop(self):
        import traceback

        logger.info(
            "STOP_REQUESTED caller_stack=\n%s",
            "".join(traceback.format_stack()),
        )
        async with self._lock:
            task = self._task
            self._stop_requested = True
            self._stop_event.set()
            if task is not None and not task.done():
                self._status = "STOPPING"
                self._worker_state = "STOPPING"

        if task is not None and not task.done():
            try:
                await asyncio.wait_for(task, timeout=60.0)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Auto-trading stop wait failed: %s", exc)
            if not task.done():
                async with self._lock:
                    self._status = "FAILED"
                    self._worker_state = "FAILED"
                    self._last_error = "Auto-trading loop did not stop in time"
                return await self.status()

        async with self._lock:
            # Pending entries must never survive Stop: they would trade later.
            await self._cancel_all_pending(reason="stop requested")
            await self._refresh_mt5_state()

            close_policy = self._stop_closes_position()
            if self._position_ticket is not None and close_policy:
                await self._close_position("stop requested")
                await self._refresh_mt5_state()

            if self._position_ticket is None:
                self._status = "STOPPED"
                self._worker_state = "STOPPED"
                self._phase = PHASE_STOPPED
            elif close_policy:
                self._status = "FAILED"
                self._worker_state = "FAILED"
                self._last_error = (
                    f"Strategy position {self._position_ticket} is still open after Stop"
                )
            else:
                self._status = "STOPPED"
                self._worker_state = "STOPPED"
                self._phase = PHASE_STOPPED
                self._last_exit_result = (
                    f"stop policy 'leave': strategy position {self._position_ticket} left open"
                )
            self._task = None
            self._next_cycle = None
            self._closed_since = None
            await self._persist_state(force=True)

        logger.info(
            "Strategy stopped (session=%s, position=%s)",
            self._session_id,
            self._position_ticket,
        )
        return await self.status()

    async def status(self):
        async with self._lock:
            return await self._build_status_unlocked()

    async def history(self):
        async with self._lock:
            items = list(self._history)
            return AutoTradingHistoryResponse(items=items, history=items, count=len(items))

    # ------------------------------------------------------------------
    # Preflight
    # ------------------------------------------------------------------
    async def _preflight(self) -> None:
        if not await self.connection.acall(self.connection.is_connected):
            raise RuntimeError("MT5 terminal is not connected")

        mt5 = self.connection.mt5
        terminal = await self.connection.acall(mt5.terminal_info)
        if terminal is None:
            raise RuntimeError("MT5 terminal info is unavailable")
        if not _get_attr(terminal, "trade_allowed", True):
            raise RuntimeError("MT5 terminal AutoTrading is disabled")

        if await self.connection.acall(mt5.account_info) is None:
            raise RuntimeError("MT5 account info is unavailable")

        requested = str(getattr(self.settings, "mt5_symbol", "") or "")
        if not _is_strategy_symbol(requested, self._strategy_symbol):
            raise RuntimeError(
                f"This strategy trades {self._strategy_symbol} only; "
                f"MT5_SYMBOL is configured as {requested!r}"
            )

        symbol = self._resolved_symbol()
        if not _is_strategy_symbol(symbol, self._strategy_symbol):
            raise RuntimeError(
                f"The resolved trading symbol {symbol!r} is not a variant of "
                f"{self._strategy_symbol}; no other instrument is traded and "
                "there is no automatic fallback"
            )

        quote = self.monitor.latest_quote()
        if quote is None or _get_attr(quote, "is_stale", False):
            raise RuntimeError("Market prices are unavailable or stale")
        if self._reference_price(quote) is None:
            raise RuntimeError(
                f"A valid {self._strategy_symbol} bid/ask is unavailable"
            )

        info = await self._get_cached_symbol_info(mt5, symbol)
        if info is None:
            raise RuntimeError("Symbol info is unavailable")
        self._adopt_price_metadata(info)

        # A chart being visible in the terminal says nothing about algorithmic
        # trading: trade_mode 0 means the broker disabled the instrument.
        trade_mode = _get_attr(info, "trade_mode", None)
        if trade_mode == 0:
            raise RuntimeError(
                f"{symbol} reports trade_mode=0: trading is disabled for this "
                "instrument; no orders will be placed"
            )
        logger.info(
            "Resolved %s metadata: digits=%s point=%s tick_size=%s "
            "volume_min=%s volume_max=%s volume_step=%s contract_size=%s "
            "trade_mode=%s stops_level=%s freeze_level=%s",
            symbol,
            self._digits,
            _get_attr(info, "point", None),
            self._tick_size,
            _get_attr(info, "volume_min", None),
            _get_attr(info, "volume_max", None),
            _get_attr(info, "volume_step", None),
            _get_attr(info, "trade_contract_size", None),
            trade_mode,
            _get_attr(info, "trade_stops_level", None),
            _get_attr(info, "trade_freeze_level", None),
        )

        volume = self.settings.auto_trade_lot_size
        vmin = _get_attr(info, "volume_min", None)
        vmax = _get_attr(info, "volume_max", None)
        vstep = _get_attr(info, "volume_step", None)
        if vmin is not None and volume < vmin:
            raise RuntimeError("Volume below broker minimum")
        if vmax is not None and volume > vmax:
            raise RuntimeError("Volume exceeds broker maximum")
        if vstep:
            base = vmin or 0.0
            steps = round((volume - base) / vstep)
            if abs(steps * vstep + base - volume) > 1e-9:
                raise RuntimeError("Volume does not match broker step")

        # Spread gate. A genuine high-spread condition is a blocked-entry state,
        # not a fatal error: the loop starts, submits nothing, and arms the cycle
        # once a fresh quote is back inside the limit. Missing quotes and invalid
        # spread inputs are a configuration/metadata fault and still fail the
        # preflight with their own, distinct message.
        check = self._evaluate_spread(quote, context="preflight")
        if check.unavailable:
            raise RuntimeError(check.reason())
        if check.blocked:
            self._last_error = check.reason()
            self._phase = PHASE_SPREAD_BLOCKED
            self._phase_before_spread_block = PHASE_INITIALIZING
            logger.warning(
                "Starting in %s: no entries will be armed until the spread "
                "returns within the configured maximum",
                PHASE_SPREAD_BLOCKED,
            )

    async def _account_balance(self) -> float | None:
        try:
            account = await self.connection.acall(self.connection.mt5.account_info)
            return _get_attr(account, "balance", None) if account else None
        except Exception:  # noqa: BLE001
            return None

    async def _account_info(self) -> Any:
        try:
            return await self.connection.acall(self.connection.mt5.account_info)
        except Exception:  # noqa: BLE001
            return None

    async def _session_loss(self) -> float | None:
        if self._start_balance is None:
            return None
        account = await self._account_info()
        if account is None:
            return None
        equity = _get_attr(account, "equity", None)
        if equity is None:
            return None
        return self._start_balance - equity

    # ------------------------------------------------------------------
    # Scheduler
    # ------------------------------------------------------------------
    async def _run(self) -> None:
        try:
            while not self._stop_requested:
                await self._step()
                if not self._stop_requested:
                    await self._sleep(self._poll_seconds())
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the loop must never die silently
            self._fail(f"Auto-trading loop failed: {type(exc).__name__}: {exc}")
            logger.exception("Auto-trading loop failed")
        finally:
            await self._shutdown_cleanup()
            async with self._lock:
                if self._worker_state != "FAILED":
                    self._worker_state = "STOPPED"
                    self._status = "STOPPED"
                    self._phase = PHASE_STOPPED
                self._task = None
                self._next_cycle = None

    async def _step(self) -> None:
        self._heartbeat_at = self._now()
        if self._stop_requested:
            return

        connected = False
        try:
            connected = await self.connection.acall(self.connection.is_connected)
        except Exception:  # noqa: BLE001
            connected = False
        if not connected:
            # The market monitor owns reconnection. Keep state, place nothing.
            if self._last_connectivity_log != "disconnected":
                logger.warning("Strategy paused: MT5 terminal is not connected")
                self._last_connectivity_log = "disconnected"
            self._last_error = "MT5 terminal is disconnected; strategy state retained"
            return
        if self._last_connectivity_log == "disconnected":
            logger.info("Strategy resumed: MT5 terminal is connected")
            self._last_connectivity_log = None

        quote = self.monitor.latest_quote()
        if quote is None or _get_attr(quote, "is_stale", False):
            if self._last_connectivity_log != "stale":
                logger.warning(
                "Strategy paused: live %s prices are unavailable or stale",
                self._strategy_symbol,
            )
                self._last_connectivity_log = "stale"
            self._last_error = "Market prices are unavailable or stale"
            return
        if self._last_connectivity_log == "stale":
            logger.info(
                "Strategy resumed: live %s prices are available",
                self._strategy_symbol,
            )
            self._last_connectivity_log = None

        await self._reconcile(quote)
        if self._phase == PHASE_ERROR or self._stop_requested:
            return

        # The spread gate protects new entries only. An open position keeps its
        # protective stop management uninterrupted, and an already-armed cycle
        # keeps waiting: no order is cancelled and no reference is reset here.
        if await self._gate_cycle_entry(quote):
            return

        if self._active_side is not None:
            await self._manage_active_position(quote)
        elif self._phase == PHASE_WAITING_ENTRY:
            await self._handle_waiting_for_entry(quote)
        elif self._phase in (PHASE_INITIALIZING, PHASE_SWITCHING):
            if self._session_completed_cycles >= self.settings.auto_trade_max_cycles:
                self._last_error = "Maximum cycles per session reached"
                self._stop_requested = True
                return
            loss = await self._session_loss()
            if loss is not None and loss >= self.settings.auto_trade_max_daily_loss:
                self._last_error = "Maximum daily loss reached"
                self._stop_requested = True
                return
            await self._initialize_cycle(quote)

        # Safety restrictions keep working exactly as before.
        if self._session_completed_cycles >= self.settings.auto_trade_max_cycles:
            self._last_error = "Maximum cycles per session reached"
            self._stop_requested = True
            return
        loss = await self._session_loss()
        if loss is not None and loss >= self.settings.auto_trade_max_daily_loss:
            self._last_error = "Maximum daily loss reached"
            self._stop_requested = True

    # ------------------------------------------------------------------
    # MT5 reconciliation primitives
    # ------------------------------------------------------------------
    async def _get_positions(self) -> list[Any]:
        mt5 = self.connection.mt5
        symbol = self._resolved_symbol()
        error: str | None = None
        positions = None
        try:
            positions = await self.connection.acall(mt5.positions_get, symbol=symbol)
        except Exception as exc:  # noqa: BLE001
            positions = None
            error = f"positions_get failed: {type(exc).__name__}: {exc}"
        if positions is None and error is None:
            # A None result from MT5 signals an API error, not an empty book.
            try:
                positions = await self.connection.acall(mt5.positions_get, symbol=symbol)
            except Exception as exc:  # noqa: BLE001
                positions = None
                error = f"positions_get failed: {type(exc).__name__}: {exc}"
        if positions is None:
            try:
                positions = await self.connection.acall(mt5.positions_get)
            except Exception as exc:  # noqa: BLE001
                positions = None
                if error is None:
                    error = f"positions_get failed: {type(exc).__name__}: {exc}"
        if positions is None:
            if error is None:
                error = "positions_get returned None (MT5 API error)"
            self._mt5_query_ok = False
            self._mt5_query_error = error
            return []
        self._mt5_query_ok = True
        self._mt5_query_error = None
        return list(positions or [])

    async def _get_orders(self) -> list[Any]:
        mt5 = self.connection.mt5
        symbol = self._resolved_symbol()
        getter = getattr(mt5, "orders_get", None)
        if getter is None:
            self._mt5_query_ok = True
            self._mt5_query_error = None
            return []
        error: str | None = None
        orders = None
        try:
            orders = await self.connection.acall(getter, symbol=symbol)
        except Exception as exc:  # noqa: BLE001
            orders = None
            error = f"orders_get failed: {type(exc).__name__}: {exc}"
        if orders is None and error is None:
            try:
                orders = await self.connection.acall(getter, symbol=symbol)
            except Exception as exc:  # noqa: BLE001
                orders = None
                error = f"orders_get failed: {type(exc).__name__}: {exc}"
        if orders is None:
            try:
                orders = await self.connection.acall(getter)
            except Exception as exc:  # noqa: BLE001
                orders = None
                if error is None:
                    error = f"orders_get failed: {type(exc).__name__}: {exc}"
        if orders is None:
            if error is None:
                error = "orders_get returned None (MT5 API error)"
            self._mt5_query_ok = False
            self._mt5_query_error = error
            return []
        self._mt5_query_ok = True
        self._mt5_query_error = None
        return list(orders or [])

    def _strategy_positions(self, positions: list[Any]) -> list[Any]:
        magic = self.settings.auto_trade_magic_number
        symbol = self._resolved_symbol()
        result = []
        for p in positions:
            if _get_attr(p, "magic", None) != magic:
                continue
            if symbol is not None and _get_attr(p, "symbol", None) not in (None, symbol):
                continue
            result.append(p)
        return result

    def _strategy_orders(self, orders: list[Any]) -> list[Any]:
        magic = self.settings.auto_trade_magic_number
        symbol = self._resolved_symbol()
        result = []
        for o in orders:
            if _get_attr(o, "magic", None) != magic:
                continue
            if symbol is not None and _get_attr(o, "symbol", None) not in (None, symbol):
                continue
            result.append(o)
        return result

    async def _refresh_mt5_state(self) -> None:
        _refresh_start_ns = time.perf_counter_ns()
        positions = self._strategy_positions(await self._get_positions())
        orders = self._strategy_orders(await self._get_orders())
        self._profile_stage("mt5_reconciliation", _refresh_start_ns, extra=f"positions={len(positions)} orders={len(orders)}")
        self._open_position_count = len(positions)
        self._pending_order_count = len(orders)
        self._position = positions[-1] if len(positions) == 1 else None
        self._orders = {
            int(ticket): order
            for order in orders
            if (ticket := _get_attr(order, "ticket", None)) is not None
        }
        self._update_order_tickets_from_orders(orders)

    def _update_order_tickets_from_orders(self, orders: list[Any]) -> None:
        for order in orders:
            side = self._side_for_order(order)
            if side is None:
                continue
            ticket = _get_attr(order, "ticket", None)
            if ticket is None:
                continue
            if side == SIDE_BUY:
                self._buy_order_ticket = int(ticket)
            else:
                self._sell_order_ticket = int(ticket)

    @staticmethod
    def _side_for_order(order: Any) -> str | None:
        order_type = _get_attr(order, "type", None)
        if order_type in (2, 4, 6):  # buy limit, buy stop, buy stop limit
            return SIDE_BUY
        if order_type in (3, 5, 7):  # sell limit, sell stop, sell stop limit
            return SIDE_SELL
        return None

    @staticmethod
    def _side_for_position(position: Any, mt5: Any) -> str | None:
        position_type = _get_attr(position, "type", None)
        if position_type == _get_attr(mt5, "ORDER_TYPE_BUY", 0):
            return SIDE_BUY
        if position_type == _get_attr(mt5, "ORDER_TYPE_SELL", 1):
            return SIDE_SELL
        return None

    def _reference_price(self, quote: Any) -> float | None:
        """The cycle reference: the current live mid price.

        A single reference is required by the strategy's symmetric formulas.
        The mid price is used so the Buy Stop and Sell Stop are equally valid
        with respect to the broker's bid/ask, then normalised to a valid tick.
        """
        bid = _get_attr(quote, "bid", None)
        ask = _get_attr(quote, "ask", None)
        if bid is not None and ask is not None and bid > 0 and ask > 0:
            reference = (float(bid) + float(ask)) / 2.0
        elif bid is not None and bid > 0:
            reference = float(bid)
        elif ask is not None and ask > 0:
            reference = float(ask)
        else:
            return None
        return self._norm(reference)

    def _favourable_price(self, quote: Any, side: str) -> float | None:
        """Price used to value an open position favourably.

        A long is valued/closed at the bid; a short at the ask.
        """
        value = _get_attr(quote, "bid" if side == SIDE_BUY else "ask", None)
        if value is None or value <= 0:
            return None
        return float(value)

    async def _history_deals_for(self, position_ticket: int) -> list[Any] | None:
        """Return the deal history for one position, or ``None`` if unavailable."""
        _history_start_ns = time.perf_counter_ns()
        mt5 = self.connection.mt5
        getter = getattr(mt5, "history_deals_get", None)
        if getter is None:
            return None
        # MT5 deal times are reported in broker-server time, which may be
        # several hours ahead of this process's UTC clock.  Keep a generous
        # window on both sides so a freshly executed stop-loss deal can never
        # fall outside the query range because of a time-zone mismatch.
        now = _utcnow()
        start = now - timedelta(days=_HISTORY_LOOKBACK_DAYS)
        end = now + timedelta(days=1)
        # MetaTrader5 expects naive datetimes; aware values are normalised to
        # naive UTC here so the broker's own time-zone handling is not confused.
        start_naive = start.replace(tzinfo=None)
        end_naive = end.replace(tzinfo=None)
        try:
            deals = await self.connection.acall(
                getter, start_naive, end_naive, position=position_ticket
            )
        except TypeError:
            try:
                deals = await self.connection.acall(getter, start_naive, end_naive)
            except Exception:  # noqa: BLE001
                return None
        except Exception:  # noqa: BLE001
            return None
        if deals is None:
            return None
        matched = []
        for deal in deals:
            position_id = _get_attr(deal, "position_id", None)
            if position_id is None:
                position_id = _get_attr(deal, "position", None)
            if position_id is None or int(position_id) == int(position_ticket):
                matched.append(deal)
        self._profile_stage("history_deals_scan", _history_start_ns, extra=f"deals={len(matched)}")
        return matched

    @staticmethod
    def _is_stop_loss_deal(deal: Any) -> bool:
        reason = _get_attr(deal, "reason", None)
        if reason is not None:
            try:
                if int(reason) == _DEAL_REASON_SL:
                    return True
            except (TypeError, ValueError):
                pass
        comment = str(_get_attr(deal, "comment", "") or "").strip().lower()
        if comment in {"sl", "stop loss", "stoploss"} or comment.startswith("sl "):
            return True
        return False

    @staticmethod
    def _deal_identifier(deal: Any) -> Any:
        ticket = _get_attr(deal, "ticket", None)
        if ticket is not None:
            return ticket
        return (
            _get_attr(deal, "position_id", None),
            _get_attr(deal, "time", None),
            _get_attr(deal, "price", None),
        )

    # ------------------------------------------------------------------
    # Persisted state
    # ------------------------------------------------------------------
    def _state_snapshot(self) -> dict[str, Any]:
        return {
            "version": 1,
            "session_id": self._session_id,
            "cycle_counter": self._cycle_counter,
            "cycle_id": self._current_cycle_id,
            "phase": self._phase,
            "reference_value": self._reference_value,
            "buy_entry": self._buy_entry,
            "buy_sl": self._buy_sl,
            "sell_entry": self._sell_entry,
            "sell_sl": self._sell_sl,
            "buy_order_ticket": self._buy_order_ticket,
            "sell_order_ticket": self._sell_order_ticket,
            "side_removed": dict(self._side_removed),
            "active_side": self._active_side,
            "position_ticket": self._position_ticket,
            "position_type": self._position_type,
            "entry_price": self._entry_price,
            "entry_volume": self._entry_volume,
            "entry_counted": self._entry_counted,
            "current_sl": self._current_sl,
            "high_water": self._high_water,
            "low_water": self._low_water,
            "break_even_active": self._break_even_active,
            "break_even_level": self._break_even_level,
            "last_processed_deal": self._last_processed_deal,
            "previous_cycle_complete": self._previous_cycle_complete,
            "completed_cycles": self._completed_cycles,
            "successful_entries": self._successful_entries,
            "failed_entries": self._failed_entries,
            "failed_exits": self._failed_exits,
            "last_entry_result": self._last_entry_result,
            "last_exit_result": self._last_exit_result,
            "last_error": self._last_error,
            "updated_at": _utcnow().isoformat(),
        }

    async def _persist_state(self, *, force: bool = False) -> None:
        store = self.store
        if store is None or not getattr(store, "enabled", False):
            return
        saver = getattr(store, "save_auto_trading_state", None)
        if saver is None:
            return
        now = self._now()
        if not force and (now - self._last_persist_at) < _PERSIST_MIN_INTERVAL_SECONDS:
            return
        self._last_persist_at = now
        try:
            await asyncio.to_thread(saver, self._state_snapshot())
        except Exception as exc:  # noqa: BLE001 - persistence must never break trading logic
            logger.warning("Could not persist auto-trading state: %s", exc)

    async def _load_persisted_state(self) -> dict[str, Any] | None:
        store = self.store
        if store is None or not getattr(store, "enabled", False):
            return None
        loader = getattr(store, "load_auto_trading_state", None)
        if loader is None:
            return None
        try:
            value = await asyncio.to_thread(loader)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read persisted auto-trading state: %s", exc)
            return None
        return value if isinstance(value, dict) else None

    def _apply_state_snapshot(self, snapshot: dict[str, Any]) -> None:
        def number(key: str) -> float | None:
            value = snapshot.get(key)
            if value is None:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        def integer(key: str) -> int | None:
            value = snapshot.get(key)
            if value is None:
                return None
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        self._cycle_counter = max(
            self._cycle_counter, integer("cycle_counter") or 0
        )
        self._current_cycle_id = snapshot.get("cycle_id") or None
        self._status = "STARTING"
        self._phase = snapshot.get("phase") or PHASE_INITIALIZING
        self._reference_value = number("reference_value")
        self._buy_entry = number("buy_entry")
        self._buy_sl = number("buy_sl")
        self._sell_entry = number("sell_entry")
        self._sell_sl = number("sell_sl")
        self._buy_order_ticket = integer("buy_order_ticket")
        self._sell_order_ticket = integer("sell_order_ticket")
        removed = snapshot.get("side_removed")
        if isinstance(removed, dict):
            self._side_removed = {
                SIDE_BUY: bool(removed.get(SIDE_BUY, False)),
                SIDE_SELL: bool(removed.get(SIDE_SELL, False)),
            }
        self._active_side = snapshot.get("active_side") or None
        self._position_ticket = integer("position_ticket")
        self._position_type = integer("position_type")
        self._entry_price = number("entry_price")
        self._entry_volume = number("entry_volume")
        self._entry_counted = bool(snapshot.get("entry_counted", False))
        self._current_sl = number("current_sl")
        self._high_water = number("high_water")
        self._low_water = number("low_water")
        self._break_even_active = bool(snapshot.get("break_even_active", False))
        self._break_even_level = number("break_even_level")
        self._last_processed_deal = snapshot.get("last_processed_deal")
        self._previous_cycle_complete = bool(
            snapshot.get("previous_cycle_complete", True)
        )
        self._completed_cycles = max(
            self._completed_cycles, integer("completed_cycles") or 0
        )
        self._successful_entries = max(
            self._successful_entries, integer("successful_entries") or 0
        )
        self._failed_entries = max(
            self._failed_entries, integer("failed_entries") or 0
        )
        self._failed_exits = max(self._failed_exits, integer("failed_exits") or 0)
        self._last_entry_result = snapshot.get("last_entry_result")
        self._last_exit_result = snapshot.get("last_exit_result")
        self._last_error = snapshot.get("last_error")

    # ------------------------------------------------------------------
    # Restoration / reconciliation after restart or reconnect
    # ------------------------------------------------------------------
    async def _restore_state_unlocked(self) -> None:
        snapshot = await self._load_persisted_state()
        if snapshot:
            self._apply_state_snapshot(snapshot)

        await self._refresh_mt5_state()
        positions = self._strategy_positions(await self._get_positions())
        orders = self._strategy_orders(await self._get_orders())

        # Prefer the exact ticket from the persisted state, then any strategy
        # position that MT5 reports.
        position = None
        if self._position_ticket is not None:
            for candidate in positions:
                if _get_attr(candidate, "ticket", None) == self._position_ticket:
                    position = candidate
                    break
        if position is None and len(positions) == 1:
            position = positions[0]
        if len(positions) > 1:
            self._fail(
                "Multiple strategy positions are open; refusing to place orders "
                "until the book is reconciled manually"
            )
            return

        if position is not None:
            await self._adopt_position(position, quote=self.monitor.latest_quote())
            # A position and a pending opposite entry must never coexist.
            await self._cancel_opposite_pending(self._active_side, reason="reconciliation")
            return

        # The persisted position closed while the backend was down.
        if self._position_ticket is not None:
            deals = await self._history_deals_for(self._position_ticket)
            sl_deal = self._stop_loss_deal(deals)
            if sl_deal is not None:
                await self._process_stop_loss_exit(
                    self._position_ticket, sl_deal, quote=None, during_restore=True
                )
            else:
                logger.warning(
                    "Persisted position %s is no longer open; no stop-loss deal "
                    "confirmed, so no switch is inferred",
                    self._position_ticket,
                )
                self._clear_active_position()

        # Adopt still-live pending entries from the persisted cycle (or from
        # MT5 itself when persistence is unavailable). Missing sides are treated
        # as already removed so a restart can never recreate a duplicate order.
        if not orders:
            self._phase = PHASE_INITIALIZING
            self._previous_cycle_complete = True
            return

        buy_order = next(
            (o for o in orders if self._side_for_order(o) == SIDE_BUY), None
        )
        sell_order = next(
            (o for o in orders if self._side_for_order(o) == SIDE_SELL), None
        )
        if buy_order is not None:
            self._buy_order_ticket = _get_attr(buy_order, "ticket", None)
        else:
            self._side_removed[SIDE_BUY] = True
        if sell_order is not None:
            self._sell_order_ticket = _get_attr(sell_order, "ticket", None)
        else:
            self._side_removed[SIDE_SELL] = True

        entry = _get_attr(buy_order or sell_order, "price", None)
        if self._reference_value is None and entry is not None:
            if buy_order is not None:
                self._reference_value = self._norm(
                    float(entry) - self._buy_entry_offset
                )
            else:
                self._reference_value = self._norm(
                    float(entry) + self._sell_entry_offset
                )
        if self._reference_value is None:
            self._phase = PHASE_INITIALIZING
            return

        if self._buy_entry is None or self._sell_entry is None:
            self._set_levels(self._build_levels(self._reference_value))
        if self._current_cycle_id is None:
            self._cycle_counter += 1
            self._current_cycle_id = f"{self._session_id}-{self._cycle_counter}"
        self._phase = PHASE_WAITING_ENTRY
        self._previous_cycle_complete = False
        logger.info(
            "Restored cycle %s with live pending orders (buy=%s, sell=%s)",
            self._current_cycle_id,
            self._buy_order_ticket,
            self._sell_order_ticket,
        )
        await self._persist_state(force=True)

    async def _reconcile(self, quote: Any) -> None:
        positions = self._strategy_positions(await self._get_positions())
        orders = self._strategy_orders(await self._get_orders())
        self._orders = {
            int(ticket): order
            for order in orders
            if (ticket := _get_attr(order, "ticket", None)) is not None
        }
        self._update_order_tickets_from_orders(orders)
        self._open_position_count = len(positions)
        self._pending_order_count = len(orders)

        if len(positions) > 1:
            self._fail(
                "Multiple strategy positions are open; refusing to place orders "
                "until the book is reconciled manually"
            )
            return

        if positions:
            position = positions[0]
            ticket = _get_attr(position, "ticket", None)
            if self._position_ticket is None or ticket != self._position_ticket:
                await self._adopt_position(position, quote)
            else:
                self._position = position
                self._refresh_position_fields(position)
            return

        if self._position_ticket is not None:
            # The position disappeared. Confirm why before doing anything else.
            await self._handle_closed_position(quote)
            return

        # No position. Track whether entries vanished without a confirmed fill.
        tracked = [
            ticket
            for ticket in (self._buy_order_ticket, self._sell_order_ticket)
            if ticket is not None
        ]
        if tracked and not any(ticket in self._orders for ticket in tracked):
            if self._orders_missing_since is None:
                self._orders_missing_since = self._now()
        else:
            self._orders_missing_since = None

    async def _adopt_position(self, position: Any, quote: Any) -> None:
        mt5 = self.connection.mt5
        side = self._side_for_position(position, mt5)
        if side is None:
            self._fail("Strategy position has an unsupported order type")
            return

        ticket = _get_attr(position, "ticket", None)
        entry_price = _get_attr(position, "price_open", None)
        if ticket is None or entry_price is None:
            self._fail("Strategy position is missing its ticket or entry price")
            return

        first_adoption = self._position_ticket != ticket or self._active_side != side
        logger.info(
            "POSITION_ADOPTED cycle=%s side=%s ticket=%s entry_price=%s first_adoption=%s",
            self._current_cycle_id,
            side.upper() if side else None,
            ticket,
            entry_price,
            first_adoption,
        )
        self._position_ticket = int(ticket)
        self._position_type = _get_attr(position, "type", None)
        self._position = position
        self._active_side = side
        self._entry_price = float(entry_price)
        self._entry_volume = _get_attr(position, "volume", None)
        self._current_profit = _get_attr(position, "profit", None)
        self._closed_since = None
        self._orders_missing_since = None
        self._phase = PHASE_BUY_OPEN if side == SIDE_BUY else PHASE_SELL_OPEN
        self._previous_cycle_complete = False

        if not self._entry_counted:
            self._entry_counted = True
            self._successful_entries += 1
            self._last_entry_result = f"{side} position opened ticket {self._position_ticket}"
            item = self._find_history_item(self._current_cycle_id)
            if item is not None:
                item.status = "filled"
                item.entry_price = self._entry_price
                item.entry_time = self._entry_time
                item.volume = self._entry_volume
            logger.info(
                "%s position opened: ticket=%s entry=%s volume=%s",
                side.upper(),
                self._position_ticket,
                self._entry_price,
                self._entry_volume,
            )

        # A recovered position may not have a cycle at all.
        if self._reference_value is None or self._buy_entry is None or self._sell_entry is None:
            reference = (
                self._entry_price - self._buy_entry_offset
                if side == SIDE_BUY
                else self._entry_price + self._sell_entry_offset
            )
            self._reference_value = self._norm(reference)
            if self._current_cycle_id is None:
                self._cycle_counter += 1
                self._current_cycle_id = f"{self._session_id}-{self._cycle_counter}"
                self._history.append(
                    AutoTradingHistoryItem(
                        cycle_id=self._current_cycle_id,
                        symbol=self._resolved_symbol(),
                        status="filled",
                        entry_price=self._entry_price,
                        entry_time=self._entry_time,
                        volume=self._entry_volume,
                    )
                )
            self._set_levels(self._build_levels(self._reference_value))
            logger.info(
                "Recovered %s position %s; derived cycle reference %s",
                side.upper(),
                self._position_ticket,
                self._reference_value,
            )

        broker_sl = _get_attr(position, "sl", None)
        # Initial protective stops are derived from the actual entry price at
        # the configured initial SL distance, not from the cycle reference, so
        # an entry that differs from the reference keeps that difference.
        if self._entry_price is not None:
            if side == SIDE_BUY:
                initial_sl = self._norm(self._entry_price - self._initial_sl_distance)
            else:
                initial_sl = self._norm(self._entry_price + self._initial_sl_distance)
        else:
            initial_sl = self._buy_sl if side == SIDE_BUY else self._sell_sl
        if self._current_sl is None:
            self._current_sl = (
                float(broker_sl) if broker_sl else float(initial_sl or 0.0) or None
            )

        # Emergency protection: never silently retain an unprotected position.
        if (broker_sl is None or float(broker_sl or 0.0) == 0.0) and initial_sl is not None:
            logger.warning(
                "Position %s adopted without a confirmed protective SL; "
                "attempting initial protection at %s",
                ticket,
                initial_sl,
            )
            await self._move_stop(position, side, float(initial_sl), reason="initial protection")

        trade_id = f"{self._session_id}-{self._cycle_counter}-{side}"
        await self._record_trade(
            {
                "trade_id": trade_id,
                "cycle_id": self._current_cycle_id,
                "symbol": self._resolved_symbol(),
                "profile": getattr(self.settings, "auto_trade_profile", None),
                "direction": side.upper(),
                "position_id": ticket,
                "status": "open",
                "entry_filled_at": datetime.now(timezone.utc).isoformat(),
                "actual_entry_price": self._entry_price,
                "actual_volume": self._entry_volume,
                "reference_price": self._reference_value,
                "initial_sl": initial_sl,
                "confirmed_initial_sl": self._current_sl,
            }
        )
        await self._record_trade_event("entry_filled", trade_id=trade_id, price=self._entry_price, position_id=ticket)

        favourable = self._favourable_price(quote, side) if quote is not None else None
        if side == SIDE_BUY:
            baseline = self._entry_price
            if favourable is not None:
                self._high_water = max(self._high_water or baseline, favourable)
            else:
                self._high_water = self._high_water or baseline
            activation_reference = self._buy_entry if self._buy_entry is not None else self._entry_price
            if not self._break_even_active and self._high_water >= buy_activation_price(
    activation_reference, self._break_even_offset
):
                self._break_even_active = True
                self._break_even_level = next_buy_stop_loss(
                    self._break_even_level, self._high_water, self._trailing_distance
                )
                logger.info(
                    "Break-even activated: BUY ticket=%s entry=%s high=%s level=%s",
                    self._position_ticket,
                    self._entry_price,
                    self._high_water,
                    self._break_even_level,
                )
            elif self._high_water is not None:
                self._break_even_level = next_buy_stop_loss(
                    self._break_even_level, self._high_water, self._trailing_distance
                )
        else:
            baseline = self._entry_price
            if favourable is not None:
                self._low_water = min(self._low_water or baseline, favourable)
            else:
                self._low_water = self._low_water or baseline
            activation_reference = self._sell_entry if self._sell_entry is not None else self._entry_price
            if not self._break_even_active and self._low_water <= sell_activation_price(
    activation_reference, self._break_even_offset
):
                self._break_even_active = True
                self._break_even_level = next_sell_stop_loss(
                    self._break_even_level, self._low_water, self._trailing_distance
                )
                logger.info(
                    "Break-even activated: SELL ticket=%s entry=%s low=%s level=%s",
                    self._position_ticket,
                    self._entry_price,
                    self._low_water,
                    self._break_even_level,
                )
            elif self._low_water is not None:
                self._break_even_level = next_sell_stop_loss(
                    self._break_even_level, self._low_water, self._trailing_distance
                )

        if self._break_even_active and self._entry_price is not None and self._break_even_level is not None:
            if side == SIDE_BUY:
                self._break_even_level = max(self._break_even_level, self._entry_price)
            else:
                self._break_even_level = min(self._break_even_level, self._entry_price)

        if broker_sl is not None and float(broker_sl) <= 0:
            # Never leave an active position without its required initial stop.
            await self._move_stop(position, side, float(initial_sl or 0.0), reason="initial stop")

        if first_adoption:
            await self._cancel_opposite_pending(side, reason="entry filled")
        await self._persist_state(force=True)

    def _refresh_position_fields(self, position: Any) -> None:
        self._entry_volume = _get_attr(position, "volume", self._entry_volume)
        self._current_profit = _get_attr(position, "profit", None)
        entry_price = _get_attr(position, "price_open", None)
        if entry_price is not None:
            self._entry_price = float(entry_price)
        broker_sl = _get_attr(position, "sl", None)
        if broker_sl:
            self._current_sl = float(broker_sl)

    # ------------------------------------------------------------------
    # Cycle initialisation / entry orders
    # ------------------------------------------------------------------
    def _build_levels(self, reference: float) -> _CycleLevels:
        """Phase 1 levels for a reference, honouring side-specific distances."""
        return build_cycle_levels(
            reference,
            self._tick_size,
            self._digits,
            buy_entry_offset=self._buy_entry_offset,
            sell_entry_offset=self._sell_entry_offset,
            initial_sl_distance=self._initial_sl_distance,
        )

    def _set_levels(self, levels: _CycleLevels) -> None:
        self._reference_value = levels.reference
        self._buy_entry = levels.buy_entry
        self._buy_sl = levels.buy_sl
        self._sell_entry = levels.sell_entry
        self._sell_sl = levels.sell_sl

    async def _initialize_cycle(self, quote: Any) -> None:
        _cycle_started_at = self._now()
        _cycle_start_ns = time.perf_counter_ns()
        _ref_start_ns = time.perf_counter_ns()
        reference = self._reference_price(quote)
        self._profile_stage("reference_price", _ref_start_ns, extra=f"reference={reference}")
        if reference is None or reference <= 0:
            self._note_error("Cannot initialise a cycle without a valid market price")
            return

        # Clean up anything belonging to a completed cycle. This only ever
        # touches pending orders, never a position's protective stop.
        await self._cancel_all_pending(reason="cleanup before new cycle")

        self._cycle_counter += 1
        self._current_cycle_id = f"{self._session_id}-{self._cycle_counter}"
        await self._record_trade_event("cycle_initialized", price=reference)
        _levels_start_ns = time.perf_counter_ns()
        levels = self._build_levels(reference)
        self._set_levels(levels)
        self._profile_stage("entry_sl_calculation", _levels_start_ns, extra=f"buy_entry={levels.buy_entry} sell_entry={levels.sell_entry}")
        self._active_side = None
        self._position_ticket = None
        self._position_type = None
        self._position = None
        self._entry_price = None
        self._entry_time = None
        self._entry_volume = None
        self._current_profit = None
        self._current_sl = None
        self._entry_counted = False
        self._high_water = None
        self._low_water = None
        self._break_even_active = False
        self._break_even_level = None
        self._last_sl_request_level = None
        self._sl_retry_at = 0.0
        self._buy_order_ticket = None
        self._sell_order_ticket = None
        self._side_removed = {SIDE_BUY: False, SIDE_SELL: False}
        logger.info(
            "CYCLE_TRANSITION cycle=%s phase=%s side_removed=%s previous_cycle_complete=%s "
            "reference=%s",
            self._current_cycle_id,
            self._phase,
            self._side_removed,
            self._previous_cycle_complete,
            reference,
        )
        self._orders_missing_since = None
        self._order_retry_at = {SIDE_BUY: 0.0, SIDE_SELL: 0.0}
        self._closed_since = None
        self._phase = PHASE_WAITING_ENTRY
        self._previous_cycle_complete = False

        self._history.append(
            AutoTradingHistoryItem(
                cycle_id=self._current_cycle_id,
                symbol=self._resolved_symbol(),
                status="pending",
            )
        )
        logger.info(
            "New cycle initialised: cycle=%s reference=%s | Buy Entry=%s Buy SL=%s | "
            "Sell Entry=%s Sell SL=%s (no take-profit)",
            self._current_cycle_id,
            levels.reference,
            levels.buy_entry,
            levels.buy_sl,
            levels.sell_entry,
            levels.sell_sl,
        )

        await self._ensure_pending_order(SIDE_BUY, quote)
        await self._ensure_pending_order(SIDE_SELL, quote)
        await self._persist_state(force=True)
        await self._record_trade_event("switching_completed", price=reference)
        self._profile_stage("cycle_init_total", _cycle_start_ns, extra=f"reference={reference}")
        logger.info(
            "CYCLE_TIMING cycle=%s elapsed_ms=%.1f reference=%s buy_entry=%s sell_entry=%s quote_bid=%s quote_ask=%s",
            self._current_cycle_id,
            (self._now() - _cycle_started_at) * 1000.0,
            reference,
            self._buy_entry,
            self._sell_entry,
            _get_attr(quote, "bid", None),
            _get_attr(quote, "ask", None),
        )

    async def _handle_waiting_for_entry(self, quote: Any) -> None:
        buy_trigger = False
        sell_trigger = False
        ask = _get_attr(quote, "ask", None)
        bid = _get_attr(quote, "bid", None)
        if ask is not None and self._buy_entry is not None:
            buy_trigger = float(ask) >= self._buy_entry - self._tolerance()
        if bid is not None and self._sell_entry is not None:
            sell_trigger = float(bid) <= self._sell_entry + self._tolerance()

        # Phase 2: remove only the unfilled opposing pending entry.
        if buy_trigger and self._sell_order_ticket is not None and not self._side_removed[SIDE_SELL]:
            self._side_removed[SIDE_SELL] = True
            await self._cancel_pending_order(self._sell_order_ticket, SIDE_SELL, reason="buy side reached")
        if sell_trigger and self._buy_order_ticket is not None and not self._side_removed[SIDE_BUY]:
            self._side_removed[SIDE_BUY] = True
            await self._cancel_pending_order(self._buy_order_ticket, SIDE_BUY, reason="sell side reached")

        # Place (or re-confirm) an entry that has not been submitted yet.
        buy_submitted = await self._ensure_pending_order(SIDE_BUY, quote)
        sell_submitted = await self._ensure_pending_order(SIDE_SELL, quote)

        # Safe recovery from repeated missed entries: if neither side could be
        # armed because the market already crossed both intended levels, abandon
        # the stale cycle only after the configured exit buffer and reinitialise
        # from the live price. This never chases a crossed price or reuses an
        # expired intent.
        both_missed = (
            self._buy_order_ticket is None
            and self._sell_order_ticket is None
            and self._active_side is None
            and self._position_ticket is None
            and (
                (not buy_submitted and not sell_submitted)
                or ("ENTRY_MISSED" in str(self._last_entry_result or ""))
            )
        )
        if both_missed:
            if self._missed_entry_since is None:
                self._missed_entry_since = self._now()
            elif (
                self._now() - self._missed_entry_since
                >= float(self.settings.auto_trade_exit_buffer_seconds or 2)
            ):
                logger.info(
                    "Reinitialising cycle after missed entry: cycle=%s buffer=%s",
                    self._current_cycle_id,
                    self.settings.auto_trade_exit_buffer_seconds,
                )
                self._missed_entry_since = None
                await self._initialize_cycle(quote)
                return
        else:
            self._missed_entry_since = None

        # Both pending entries disappearing without a position is an
        # inconsistent broker state. Never guess: only re-initialise after the
        # confirmation window, with a freshly-read live price.
        if (
            self._buy_order_ticket is not None
            and self._sell_order_ticket is not None
            and self._orders_missing_since is not None
            and (self._now() - self._orders_missing_since) >= _CLOSED_CONFIRM_TIMEOUT_SECONDS
        ):
            logger.warning(
                "Both pending entries disappeared without a confirmed fill; "
                "initialising a fresh cycle from the live price"
            )
            await self._initialize_cycle(quote)

    async def _ensure_pending_order(self, side: str, quote: Any) -> bool:
        _intent_id = self._next_intent_id(side)
        _entry_start_ns = time.perf_counter_ns()
        logger.debug(
            "ENTRY_INTENT cycle=%s side=%s phase=%s side_removed=%s active_side=%s "
            "buy_ticket=%s sell_ticket=%s level=%s sl=%s",
            self._current_cycle_id,
            side.upper(),
            self._phase,
            self._side_removed.get(side),
            self._active_side,
            self._buy_order_ticket,
            self._sell_order_ticket,
            self._buy_entry if side == SIDE_BUY else self._sell_entry,
            self._buy_sl if side == SIDE_BUY else self._sell_sl,
        )
        if self._stop_requested or self._active_side is not None:
            return False
        if self._side_removed[side]:
            return False

        ticket = self._buy_order_ticket if side == SIDE_BUY else self._sell_order_ticket
        if ticket is not None and int(ticket) in self._orders:
            # Idempotency: an order for this side already exists with a tracked
            # ticket. Verify its price/SL already match the intended values;
            # if so, retain it and do not recreate.
            existing = self._orders.get(int(ticket))
            intended_price = self._buy_entry if side == SIDE_BUY else self._sell_entry
            intended_sl = self._buy_sl if side == SIDE_BUY else self._sell_sl
            if existing is not None and intended_price is not None:
                existing_price = _get_attr(existing, "price", None)
                existing_sl = _get_attr(existing, "sl", None)
                tol = self._tolerance()
                if (
                    existing_price is not None
                    and abs(float(existing_price) - float(intended_price)) <= tol
                    and (intended_sl is None or existing_sl is None or abs(float(existing_sl) - float(intended_sl)) <= tol)
                ):
                    logger.debug(
                        "Retaining existing %s Stop ticket=%s: price=%s sl=%s already match intended",
                        side.upper(),
                        ticket,
                        existing_price,
                        existing_sl,
                    )
                    return True
            return True
        # Adopt any untracked order of this side reported by MT5 instead of
        # placing a duplicate.
        for order in self._orders.values():
            if self._side_for_order(order) != side:
                continue
            adopted = _get_attr(order, "ticket", None)
            if adopted is None:
                continue
            if side == SIDE_BUY:
                self._buy_order_ticket = int(adopted)
            else:
                self._sell_order_ticket = int(adopted)
            logger.info(
                "Adopted existing %s Stop ticket=%s instead of placing a duplicate",
                side.upper(),
                adopted,
            )
            return True

        if ticket is not None:
            # Tracked ticket no longer live; do not duplicate here.
            return False

        if self._now() < self._order_retry_at[side]:
            return False

        # Final safeguard: an entry is never submitted on a quote whose spread
        # is above the configured maximum, or whose spread cannot be verified.
        # This is independent of the phase, so no code path can bypass it.
        # Bounded retries with a fresh quote handle transient broker errors
        # during rapid price movement without duplicating orders.
        _ENTRY_MAX_ATTEMPTS = 3
        _TRANSIENT_RETCODES = {10004, 10006, 10020, 10021, 10031}

        # Broker symbol metadata (tick size, stops/freeze levels) is stable for
        # the resolved symbol, so it is read once per entry intent instead of
        # on every retry attempt.
        mt5 = self.connection.mt5
        _meta_start_ns = time.perf_counter_ns()
        _resolved = self._resolved_symbol()
        info = await self._get_cached_symbol_info(mt5, _resolved)
        self._adopt_price_metadata(info)
        self._profile_stage("symbol_metadata", _meta_start_ns, side=side, extra=f"stops_level={_get_attr(info, 'trade_stops_level', None)} freeze_level={_get_attr(info, 'trade_freeze_level', None)}")
        point_value = _get_attr(info, "point", None) or self._tick_size
        try:
            point_value = float(point_value) if point_value is not None else None
        except (TypeError, ValueError):
            point_value = None
        stops_level = _get_attr(info, "trade_stops_level", None)
        freeze_level = _get_attr(info, "trade_freeze_level", None)
        try:
            stops_value = int(stops_level) if stops_level is not None else 0
        except (TypeError, ValueError):
            stops_value = 0
        for _attempt in range(1, _ENTRY_MAX_ATTEMPTS + 1):
            # Reconcile before every attempt so a delayed response can never
            # cause a duplicate order.
            await self._refresh_mt5_state()
            for order in list(self._orders.values()):
                if self._side_for_order(order) != side:
                    continue
                adopted = _get_attr(order, "ticket", None)
                if adopted is None:
                    continue
                if side == SIDE_BUY:
                    self._buy_order_ticket = int(adopted)
                else:
                    self._sell_order_ticket = int(adopted)
                logger.info(
                    "ENTRY_CONFIRMED (existing) %s Stop ticket=%s adopted on attempt %s",
                    side.upper(), adopted, _attempt,
                )
                return True

            fresh_quote = self.monitor.latest_quote()
            if fresh_quote is None or _get_attr(fresh_quote, "is_stale", False):
                logger.info("ENTRY_BLOCKED %s: quote unavailable or stale", side.upper())
                self._last_error = "Market prices are unavailable or stale"
                return False

            _spread_start_ns = time.perf_counter_ns()
            spread = self._evaluate_spread(
                fresh_quote, context=f"{side.upper()} Stop submission"
            )
            self._profile_stage("spread_validation", _spread_start_ns, side=side, intent_id=_intent_id, extra=f"outcome={spread.outcome}")
            if spread.outcome != SPREAD_OK:
                self._last_error = spread.reason()
                logger.info("ENTRY_BLOCKED %s: %s", side.upper(), spread.reason())
                return False
            self._clear_spread_error()

            level = self._buy_entry if side == SIDE_BUY else self._sell_entry
            stop_loss = self._buy_sl if side == SIDE_BUY else self._sell_sl
            if level is None or stop_loss is None:
                return False

            # Broker metadata was read once before this retry loop.
            price = self._norm(level)
            sl = self._norm(stop_loss)
            if price is None or sl is None:
                return False

            # A brand-new tick, read immediately before validating: a cached
            # monitor quote is exactly what turns an aggressive XAUUSD move
            # into "retcode=10015 comment=Invalid price".
            _tick_start_ns = time.perf_counter_ns()
            tick = await self._read_live_tick()
            self._profile_stage("fresh_tick", _tick_start_ns, side=side, intent_id=_intent_id, extra=f"usable={'yes' if tick is not None else 'no'}")
            quote_source = "mt5 tick"
            if tick is None:
                tick = fresh_quote
                quote_source = "monitor quote (no usable live tick)"
            bid, ask = self._market_bid_ask(tick)
            if bid is None or ask is None or ask < bid:
                # Without a trustworthy Bid/Ask the request cannot be checked,
                # and an unvalidated request is never sent.
                if await self._reconcile_entry(side):
                    return True
                self._failed_entries += 1
                self._order_retry_at[side] = self._now() + _ORDER_RETRY_SECONDS
                self._note_error(
                    f"{side.upper()} Stop not submitted: no usable Bid/Ask to validate against"
                )
                return False
            tick_time = _get_attr(tick, "time", None)

            _gate_start_ns = time.perf_counter_ns()
            gate = check_stop_order(
                side,
                price,
                sl,
                bid,
                ask,
                point=point_value,
                stops_level=stops_value,
            )
            self._profile_stage("entry_validation", _gate_start_ns, side=side, intent_id=_intent_id, extra=f"outcome={gate.outcome}")
            if not gate.ok:
                # Reconcile before deciding: a delayed broker response must
                # never turn a rejection into a duplicate order.
                if await self._reconcile_entry(side):
                    return True
                if gate.outcome == ENTRY_CROSSED:
                    await self._record_entry_missed(
                        side,
                        price,
                        (
                            f"cycle={self._current_cycle_id} reference={self._reference_value} "
                            f"intended={price} bid={bid:g} ask={ask:g} "
                            f"quote_source={quote_source} - {gate.reason}"
                        ),
                    )
                    return False
                self._failed_entries += 1
                self._order_retry_at[side] = self._now() + _ORDER_RETRY_SECONDS
                self._note_error(f"{side.upper()} Stop not submitted: {gate.reason}")
                return False

            order_type = (
                _get_attr(mt5, "ORDER_TYPE_BUY_STOP", 4)
                if side == SIDE_BUY
                else _get_attr(mt5, "ORDER_TYPE_SELL_STOP", 5)
            )
            prefix = "AU_M1_B" if side == SIDE_BUY else "AU_M1_S"
            request = {
                "action": _get_attr(mt5, "TRADE_ACTION_PENDING", 5),
                "symbol": self._resolved_symbol(),
                "volume": self.settings.auto_trade_lot_size,
                "type": order_type,
                "price": price,
                "sl": sl,
                "tp": 0.0,
                "deviation": self.settings.auto_trade_max_entry_deviation_points,
                "magic": self.settings.auto_trade_magic_number,
                "comment": _make_comment(prefix, self._cycle_counter),
                "type_time": _get_attr(mt5, "ORDER_TIME_GTC", 0),
                "type_filling": self._filling_mode(mt5, info),
            }

            # Preflight validation with MT5, on the actual normalised request.
            check_retcode = 0
            check_comment = "order_check unavailable"
            checker = getattr(mt5, "order_check", None)
            if checker is not None:
                _order_check_start_ns = time.perf_counter_ns()
                try:
                    check_result = await self.connection.acall(checker, request)
                except Exception as exc:  # noqa: BLE001
                    check_result = None
                    check_exc = exc
                else:
                    check_exc = None
                self._profile_stage("order_check", _order_check_start_ns, side=side, intent_id=_intent_id, extra=f"retcode={_get_attr(check_result, 'retcode', None) if check_exc is None else 'exc'}")
                if check_exc is not None:
                    check_comment = "order_check raised an exception"
                    logger.warning("ORDER_CHECK_FAILED %s: %s", side.upper(), check_exc)
                else:
                    check_retcode = _get_attr(check_result, "retcode", 0)
                    check_comment = _get_attr(check_result, "comment", None) or "no comment"
                    if check_retcode not in (0, None):
                        comment = check_comment
                        logger.warning(
                            "ORDER_CHECK_FAILED %s: retcode=%s comment=%s",
                            side.upper(), check_retcode, comment,
                        )
                        if check_retcode in _TRANSIENT_RETCODES and _attempt < _ENTRY_MAX_ATTEMPTS:
                            await self._sleep(_ORDER_RETRY_SECONDS)
                            continue
                        # The market can move while order_check runs. Reconcile
                        # first, then rebuild from a fresh tick instead of
                        # resending a request the broker already refused.
                        if _price_rejected(check_retcode):
                            recovery_tick = await self._read_live_tick() or fresh_quote
                            recovery_bid, recovery_ask = self._market_bid_ask(recovery_tick)
                            if await self._reconcile_entry(side):
                                return True
                            if recovery_bid is not None and recovery_ask is not None:
                                recovery = check_stop_order(
                                    side,
                                    price,
                                    sl,
                                    recovery_bid,
                                    recovery_ask,
                                    point=point_value,
                                    stops_level=stops_value,
                                )
                                if recovery.outcome == ENTRY_CROSSED:
                                    await self._record_entry_missed(
                                        side,
                                        price,
                                        (
                                            f"cycle={self._current_cycle_id} "
                                            f"reference={self._reference_value} intended={price} "
                                            f"bid={recovery_bid:g} ask={recovery_ask:g} - "
                                            f"order_check retcode={check_retcode}: {recovery.reason}"
                                        ),
                                    )
                                    return False
                                if _attempt < _ENTRY_MAX_ATTEMPTS:
                                    await self._sleep(_ORDER_RETRY_SECONDS)
                                    continue
                        self._failed_entries += 1
                        self._order_retry_at[side] = self._now() + _ORDER_RETRY_SECONDS
                        self._note_error(
                            f"{side.upper()} Stop order_check rejected: retcode={check_retcode} comment={comment}"
                        )
                        return False

            # The market can also move between order_check and order_send.
            # Read one more tick and send only while the request is still valid.
            _final_tick_start_ns = time.perf_counter_ns()
            pre_send_tick = await self._read_live_tick() or fresh_quote
            self._profile_stage("final_revalidation_tick", _final_tick_start_ns, side=side, intent_id=_intent_id, extra="pre_send")
            pre_bid, pre_ask = self._market_bid_ask(pre_send_tick)
            if pre_bid is None or pre_ask is None:
                if await self._reconcile_entry(side):
                    return True
                self._failed_entries += 1
                self._order_retry_at[side] = self._now() + _ORDER_RETRY_SECONDS
                self._note_error(
                    f"{side.upper()} Stop not submitted: Bid/Ask unavailable before order_send"
                )
                return False
            _final_gate_start_ns = time.perf_counter_ns()
            pre_gate = check_stop_order(
                side,
                price,
                sl,
                pre_bid,
                pre_ask,
                point=point_value,
                stops_level=stops_value,
            )
            self._profile_stage("final_revalidation", _final_gate_start_ns, side=side, intent_id=_intent_id, extra=f"outcome={pre_gate.outcome}")
            if not pre_gate.ok:
                if await self._reconcile_entry(side):
                    return True
                if pre_gate.outcome == ENTRY_CROSSED:
                    await self._record_entry_missed(
                        side,
                        price,
                        (
                            f"cycle={self._current_cycle_id} reference={self._reference_value} "
                            f"intended={price} bid={pre_bid:g} ask={pre_ask:g} "
                            f"moved after order_check - {pre_gate.reason}"
                        ),
                    )
                    return False
                if _attempt < _ENTRY_MAX_ATTEMPTS:
                    await self._sleep(_ORDER_RETRY_SECONDS)
                    continue
                self._failed_entries += 1
                self._order_retry_at[side] = self._now() + _ORDER_RETRY_SECONDS
                self._note_error(
                    f"{side.upper()} Stop not submitted: {pre_gate.reason}"
                )
                return False
            bid, ask = pre_bid, pre_ask

            existing_ticket = self._buy_order_ticket if side == SIDE_BUY else self._sell_order_ticket
            logger.info(
                "MT5 entry submit: ts=%s profile=%s symbol=%s action=PENDING %s "
                "cycle=%s reference=%s intended_entry=%s intended_sl=%s "
                "magic=%s ticket_before=%s price=%s sl=%s tp=0.0 "
                "attempt=%s quote_source=%s tick_time=%s bid=%s ask=%s "
                "quote_bid=%s quote_ask=%s spread_points=%s point=%s digits=%s "
                "tick_size=%s stops_level=%s freeze_level=%s required_stop=%s "
                "stop_gap=%s crossed=%s max_spread=%s deviation=%s",
                _utcnow().isoformat(),
                getattr(self.settings, "auto_trade_profile", None),
                self._resolved_symbol(),
                side.upper(),
                self._current_cycle_id,
                self._reference_value,
                level,
                stop_loss,
                self.settings.auto_trade_magic_number,
                existing_ticket,
                price,
                sl,
                _attempt,
                quote_source,
                tick_time,
                bid,
                ask,
                _get_attr(fresh_quote, "bid", None),
                _get_attr(fresh_quote, "ask", None),
                _get_attr(fresh_quote, "spread_points", None),
                point_value,
                self._digits,
                self._tick_size,
                stops_level,
                freeze_level,
                gate.required_gap,
                pre_gate.gap,
                "no",
                getattr(self.settings, "auto_trade_max_spread_points", None),
                self.settings.auto_trade_max_entry_deviation_points,
            )
            logger.info(
                "ORDER_CHECK_OK %s: symbol=%s cycle=%s retcode=%s comment=%s "
                "requested_price=%s requested_sl=%s bid=%s ask=%s",
                side.upper(),
                self._resolved_symbol(),
                self._current_cycle_id,
                check_retcode,
                check_comment,
                price,
                sl,
                bid,
                ask,
            )
            await self._record_trade_event("entry_submitted", price=price, details=side.upper())
            self._last_order_attempt = f"{side.upper()} Stop cycle={self._current_cycle_id}"
            try:
                _order_send_start_ns = time.perf_counter_ns()
                result = await self.connection.acall(mt5.order_send, request)
                self._profile_stage("order_send", _order_send_start_ns, side=side, intent_id=_intent_id, extra=f"retcode={_get_attr(result, 'retcode', None)}")
            except Exception as exc:  # noqa: BLE001 - confirm before retrying
                self._profile_stage("order_send", _order_send_start_ns, side=side, intent_id=_intent_id, extra=f"exception={type(exc).__name__}")
                await self._refresh_mt5_state()
                confirmed = await self._find_confirmed_entry(side)
                if confirmed is not None:
                    self._last_entry_result = (
                        f"{side} entry ambiguous but confirmed after order_send error"
                    )
                    logger.warning(
                        "ENTRY_CONFIRMED %s: submission raised (%s) but MT5 reports the order/position",
                        side.upper(), exc,
                    )
                    return True
                if _attempt < _ENTRY_MAX_ATTEMPTS:
                    await self._sleep(_ORDER_RETRY_SECONDS)
                    continue
                self._failed_entries += 1
                self._order_retry_at[side] = self._now() + _ORDER_RETRY_SECONDS
                self._note_error(f"{side.upper()} Stop submission failed: {exc}")
                return False

            if result is None:
                confirmed = await self._wait_for_confirmed_entry(side, None)
                if confirmed is not None:
                    self._last_entry_result = (
                        f"{side} entry ambiguous but confirmed by MT5"
                    )
                    logger.warning(
                        "ENTRY_CONFIRMED %s: result unavailable but MT5 confirms",
                        side.upper(),
                    )
                    return True
                if _attempt < _ENTRY_MAX_ATTEMPTS:
                    await self._sleep(_ORDER_RETRY_SECONDS)
                    continue
                self._failed_entries += 1
                self._order_retry_at[side] = self._now() + _ORDER_RETRY_SECONDS
                self._note_error(f"{side.upper()} Stop result was unavailable and unconfirmed")
                return False

            logger.info(
                "MT5 entry result: ts=%s profile=%s symbol=%s %s retcode=%s comment=%s "
                "order=%s deal=%s position=%s price=%s volume=%s bid=%s ask=%s "
                "attempt=%s crossed=%s",
                _utcnow().isoformat(),
                getattr(self.settings, "auto_trade_profile", None),
                self._resolved_symbol(),
                side.upper(),
                _get_attr(result, "retcode", None),
                _get_attr(result, "comment", None),
                _get_attr(result, "order", None),
                _get_attr(result, "deal", None),
                _get_attr(result, "position", None),
                _get_attr(result, "price", None),
                _get_attr(result, "volume", None),
                _get_attr(result, "bid", None),
                _get_attr(result, "ask", None),
                _attempt,
                "no",
            )

            retcode = _get_attr(result, "retcode", None)
            done = _get_attr(mt5, "TRADE_RETCODE_DONE", 10009)
            partial = _get_attr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010)
            if retcode not in (done, partial):
                comment = _get_attr(result, "comment", None) or "no comment"
                logger.warning(
                    "ORDER_SEND_FAILED %s: retcode=%s comment=%s", side.upper(), retcode, comment,
                )
                if retcode in _TRANSIENT_RETCODES and _attempt < _ENTRY_MAX_ATTEMPTS:
                    await self._sleep(_ORDER_RETRY_SECONDS)
                    continue
                # A price/stops rejection means the market moved between the
                # last check and the submission. Reconcile first, then either
                # adopt what the broker already holds or rebuild the request
                # from a fresh tick - never resend the identical invalid one.
                price_rejected = _price_rejected(retcode)
                if price_rejected:
                    recovery_tick = await self._read_live_tick() or fresh_quote
                    recovery_bid, recovery_ask = self._market_bid_ask(recovery_tick)
                    if await self._reconcile_entry(side):
                        return True
                    if recovery_bid is not None and recovery_ask is not None:
                        recovery = check_stop_order(
                            side,
                            price,
                            sl,
                            recovery_bid,
                            recovery_ask,
                            point=point_value,
                            stops_level=stops_value,
                        )
                        if recovery.outcome == ENTRY_CROSSED:
                            await self._record_entry_missed(
                                side,
                                price,
                                (
                                    f"cycle={self._current_cycle_id} "
                                    f"reference={self._reference_value} intended={price} "
                                    f"bid={recovery_bid:g} ask={recovery_ask:g} "
                                    f"order_send retcode={retcode} comment={comment} - "
                                    f"{recovery.reason}"
                                ),
                            )
                            return False
                        if _attempt < _ENTRY_MAX_ATTEMPTS:
                            await self._sleep(_ORDER_RETRY_SECONDS)
                            continue
                self._failed_entries += 1
                self._order_retry_at[side] = self._now() + _ORDER_RETRY_SECONDS
                self._note_error(
                    f"{side.upper()} Stop rejected: retcode={retcode} comment={comment}"
                )
                await self._record_trade_event(
                    "entry_rejected", price=price, result_code=retcode, details=comment
                )
                return False

            expected_ticket = _get_attr(result, "order", None)
            _confirm_start_ns = time.perf_counter_ns()
            confirmed = await self._wait_for_confirmed_entry(side, expected_ticket)
            self._profile_stage("broker_confirmation", _confirm_start_ns, side=side, intent_id=_intent_id, extra=f"confirmed={'yes' if confirmed is not None else 'no'}")
            if confirmed is None:
                logger.warning(
                    "ENTRY_EXPIRED_OR_CANCELLED %s: order accepted but not confirmed",
                    side.upper(),
                )
                if _attempt < _ENTRY_MAX_ATTEMPTS:
                    await self._sleep(_ORDER_RETRY_SECONDS)
                    continue
                self._failed_entries += 1
                self._order_retry_at[side] = self._now() + _ORDER_RETRY_SECONDS
                self._note_error(
                    f"{side.upper()} Stop reported done but no MT5 order/position was found"
                )
                return False

            kind, value = confirmed
            if kind == "order":
                if side == SIDE_BUY:
                    self._buy_order_ticket = int(_get_attr(value, "ticket", value))
                else:
                    self._sell_order_ticket = int(_get_attr(value, "ticket", value))
                self._last_entry_result = (
                    f"{side} Stop confirmed ticket "
                    f"{self._buy_order_ticket if side == SIDE_BUY else self._sell_order_ticket}"
                )
                self._degraded = False
                self._last_error = None
                logger.info(
                    "ENTRY_CONFIRMED %s: ticket=%s price=%s sl=%s",
                    side.upper(),
                    self._buy_order_ticket if side == SIDE_BUY else self._sell_order_ticket,
                    price,
                    sl,
                )
                await self._record_trade_event(
                    "entry_confirmed",
                    price=price,
                    order_ticket=self._buy_order_ticket if side == SIDE_BUY else self._sell_order_ticket,
                    details=side.upper(),
                )
            else:
                logger.info(
                    "%s Stop was executed immediately; position confirmed",
                    side.upper(),
                )
                await self._adopt_position(value, quote)
            await self._persist_state(force=True)
            return True

        self._failed_entries += 1
        self._order_retry_at[side] = self._now() + _ORDER_RETRY_SECONDS
        self._note_error(f"{side.upper()} Stop submission exhausted retries")
        return False

    async def _wait_for_confirmed_entry(
        self, side: str, expected_ticket: Any
    ) -> tuple[str, Any] | None:
        deadline = self._now() + _CONFIRM_TIMEOUT_SECONDS
        while True:
            orders = self._strategy_orders(await self._get_orders())
            positions = self._strategy_positions(await self._get_positions())
            for order in orders:
                if self._side_for_order(order) != side:
                    continue
                ticket = _get_attr(order, "ticket", None)
                if expected_ticket in (None, 0) or ticket == expected_ticket:
                    self._orders = {
                        int(t): o
                        for o in orders
                        if (t := _get_attr(o, "ticket", None)) is not None
                    }
                    return "order", order
            if positions:
                self._orders = {}
                return "position", positions[0]
            if self._now() >= deadline:
                return None
            await self._sleep(_CONFIRM_POLL_SECONDS)

    async def _find_confirmed_entry(self, side: str) -> tuple[str, Any] | None:
        orders = self._strategy_orders(await self._get_orders())
        for order in orders:
            if self._side_for_order(order) == side:
                return "order", order
        positions = self._strategy_positions(await self._get_positions())
        if positions:
            return "position", positions[0]
        return None

    # ------------------------------------------------------------------
    # Removing phase
    # ------------------------------------------------------------------
    async def _cancel_opposite_pending(self, active_side: str | None, *, reason: str) -> None:
        if active_side == SIDE_BUY:
            self._side_removed[SIDE_SELL] = True
            if self._sell_order_ticket is not None:
                await self._cancel_pending_order(self._sell_order_ticket, SIDE_SELL, reason=reason)
        elif active_side == SIDE_SELL:
            self._side_removed[SIDE_BUY] = True
            if self._buy_order_ticket is not None:
                await self._cancel_pending_order(self._buy_order_ticket, SIDE_BUY, reason=reason)
        await self._record_trade_event("opposing_order_cancelled", details=reason)

    async def _cancel_all_pending(self, *, reason: str) -> None:
        await self._refresh_mt5_state()
        for order in list(self._orders.values()):
            side = self._side_for_order(order)
            ticket = _get_attr(order, "ticket", None)
            if side is None or ticket is None:
                continue
            await self._cancel_pending_order(int(ticket), side, reason=reason)

    async def _cancel_pending_order(self, ticket: int, side: str, *, reason: str) -> bool:
        # Re-read MT5 first: an order that already filled must not be "removed",
        # and an already-cancelled order must not produce a second request.
        await self._refresh_mt5_state()
        if int(ticket) not in self._orders:
            self._set_pending_ticket(side, None)
            return True

        mt5 = self.connection.mt5
        logger.info(
            "MT5 entry remove: ts=%s profile=%s symbol=%s action=REMOVE %s "
            "ticket=%s magic=%s reason=%s",
            _utcnow().isoformat(),
            getattr(self.settings, "auto_trade_profile", None),
            self._resolved_symbol(),
            side.upper(),
            ticket,
            self.settings.auto_trade_magic_number,
            reason,
        )
        request = {
            "action": _get_attr(mt5, "TRADE_ACTION_REMOVE", 8),
            "order": int(ticket),
        }
        try:
            result = await self.connection.acall(mt5.order_send, request)
        except Exception as exc:  # noqa: BLE001
            await self._refresh_mt5_state()
            if int(ticket) not in self._orders:
                self._set_pending_ticket(side, None)
                return True
            self._note_error(f"Could not remove {side} Stop {ticket}: {exc}")
            return False

        logger.info(
            "MT5 entry remove result: ts=%s profile=%s symbol=%s %s ticket=%s "
            "retcode=%s comment=%s",
            _utcnow().isoformat(),
            getattr(self.settings, "auto_trade_profile", None),
            self._resolved_symbol(),
            side.upper(),
            ticket,
            _get_attr(result, "retcode", None),
            _get_attr(result, "comment", None),
        )
        retcode = _get_attr(result, "retcode", None)
        done = _get_attr(mt5, "TRADE_RETCODE_DONE", 10009)
        if result is not None and retcode not in (done,):
            # A "not found" result still means the order is not live.
            await self._refresh_mt5_state()
            if int(ticket) not in self._orders:
                self._set_pending_ticket(side, None)
                return True
            comment = _get_attr(result, "comment", None) or "no comment"
            self._note_error(
                f"{side.upper()} Stop removal rejected: retcode={retcode} comment={comment}"
            )
            return False

        # Confirm the cancellation with MT5 before reporting it.
        deadline = self._now() + _CONFIRM_TIMEOUT_SECONDS
        while True:
            await self._refresh_mt5_state()
            if int(ticket) not in self._orders:
                self._set_pending_ticket(side, None)
                logger.info(
                    "Pending entry removed: %s Stop ticket=%s (%s)",
                    side.upper(),
                    ticket,
                    reason,
                )
                await self._persist_state(force=True)
                return True
            if self._now() >= deadline:
                break
            await self._sleep(_CONFIRM_POLL_SECONDS)
        self._note_error(f"{side.upper()} Stop {ticket} removal was not confirmed by MT5")
        return False

    def _set_pending_ticket(self, side: str, ticket: int | None) -> None:
        if side == SIDE_BUY:
            self._buy_order_ticket = ticket
        else:
            self._sell_order_ticket = ticket
        if ticket is not None:
            self._side_removed[side] = False

    # ------------------------------------------------------------------
    # Active position management (break-even trailing)
    # ------------------------------------------------------------------
    async def _manage_active_position(self, quote: Any) -> None:
        _be_start_ns = time.perf_counter_ns()
        position = self._position
        if position is None or self._active_side is None:
            return
        side = self._active_side
        entry = self._entry_price
        if entry is None:
            return

        favourable = self._favourable_price(quote, side)
        if favourable is None:
            return

        changed = False
        if side == SIDE_BUY:
            high = max(self._high_water if self._high_water is not None else entry, favourable)
            if high != self._high_water:
                self._high_water = high
                changed = True
            activation_reference = self._buy_entry if self._buy_entry is not None else entry
            if not self._break_even_active and high >= buy_activation_price(
    activation_reference, self._break_even_offset
):
                self._break_even_active = True
                changed = True
                logger.info(
                    "Break-even activated: BUY ticket=%s entry=%s activation=%s",
                    self._position_ticket,
                    entry,
                    self._norm(buy_activation_price(entry)),
                )
                await self._record_trade_event("break_even_activated", price=self._break_even_level, position_id=self._position_ticket, details="buy")
            if self._break_even_active and self._high_water is not None:
                trail = await self._effective_trailing_distance()
                previous_level = self._break_even_level
                self._break_even_level = next_buy_stop_loss(
                    previous_level, self._high_water, trail
                )
                if (
                    self._last_trail_atr is not None
                    and self._break_even_level is not None
                    and (previous_level is None or self._break_even_level != previous_level)
                ):
                    logger.info(
                        "Trailing target updated: BUY ticket=%s bid=%s atr=%s "
                        "effective_trail=%s desired_sl=%s confirmed_sl=%s "
                        "in_flight=%s pending=%s",
                        self._position_ticket,
                        favourable,
                        self._last_trail_atr,
                        trail,
                        self._break_even_level,
                        self._current_sl,
                        self._sl_request_in_flight,
                        self._pending_sl_target,
                    )
                if self._entry_price is not None and self._break_even_level is not None:
                    self._break_even_level = max(
                        self._break_even_level, self._entry_price
                    )
                target = self._current_sl
                if self._break_even_level is not None and (
                    target is None or self._break_even_level > target
                ):
                    target = self._break_even_level
                if target is not None and self._is_protective_move(side, target):
                    await self._move_stop(position, side, target, reason="break-even trailing")
        else:
            low = min(self._low_water if self._low_water is not None else entry, favourable)
            if low != self._low_water:
                self._low_water = low
                changed = True
            activation_reference = self._sell_entry if self._sell_entry is not None else entry
            if not self._break_even_active and low <= sell_activation_price(
    activation_reference, self._break_even_offset
):
                self._break_even_active = True
                changed = True
                logger.info(
                    "Break-even activated: SELL ticket=%s entry=%s activation=%s",
                    self._position_ticket,
                    entry,
                    self._norm(sell_activation_price(entry)),
                )
                await self._record_trade_event("break_even_activated", price=self._break_even_level, position_id=self._position_ticket, details="sell")
            if self._break_even_active and self._low_water is not None:
                trail = await self._effective_trailing_distance()
                previous_level = self._break_even_level
                self._break_even_level = next_sell_stop_loss(
                    previous_level, self._low_water, trail
                )
                if (
                    self._last_trail_atr is not None
                    and self._break_even_level is not None
                    and (previous_level is None or self._break_even_level != previous_level)
                ):
                    logger.info(
                        "Trailing target updated: SELL ticket=%s ask=%s atr=%s "
                        "effective_trail=%s desired_sl=%s confirmed_sl=%s "
                        "in_flight=%s pending=%s",
                        self._position_ticket,
                        favourable,
                        self._last_trail_atr,
                        trail,
                        self._break_even_level,
                        self._current_sl,
                        self._sl_request_in_flight,
                        self._pending_sl_target,
                    )
                if self._entry_price is not None and self._break_even_level is not None:
                    self._break_even_level = min(
                        self._break_even_level, self._entry_price
                    )
                target = self._current_sl
                if self._break_even_level is not None and (
                    target is None or self._break_even_level < target
                ):
                    target = self._break_even_level
                if target is not None and self._is_protective_move(side, target):
                    await self._move_stop(position, side, target, reason="break-even trailing")

        if changed:
            await self._persist_state()
        self._profile_stage("break_even_trailing", _be_start_ns, side=side, extra=f"changed={changed}")
    async def _effective_trailing_distance(self) -> float:
        cap = float(self._trailing_distance)
        # "static" and "fixed" both mean an exact configured trailing gap.
        if self._trailing_mode in ("static", "fixed"):
            return cap
        atr = await self._calculate_trail_atr()
        if atr is not None:
            self._last_trail_atr = atr
        return effective_trailing_distance(
            self._last_trail_atr, self._trail_atr_multiplier, cap
        )

    async def _calculate_trail_atr(self) -> float | None:
        try:
            mt5 = self.connection.mt5
            symbol = self._resolved_symbol()
            if not symbol:
                return None
            tf = get_timeframe("M1").mt5_value
            rates = await self.connection.acall(
                mt5.copy_rates_from_pos, symbol, tf, 0, self._trail_atr_period + 2
            )
            return calculate_atr(rates, self._trail_atr_period)
        except Exception:  # noqa: BLE001 - defensive
            return None

    def _is_more_protective(self, side: str, target: float, pending: float | None) -> bool:
        if pending is None:
            return True
        tolerance = self._tolerance()
        if side == SIDE_BUY:
            return target > pending + tolerance
        return target < pending - tolerance

    def _is_protective_move(self, side: str, target: float) -> bool:
        if self._current_sl is None:
            return True
        tolerance = self._tolerance()
        if side == SIDE_BUY:
            return target > self._current_sl + tolerance
        return target < self._current_sl - tolerance

    async def _validate_stop_target(
        self, position_ticket: int, side: str, target: float
    ) -> StopMoveValidation:
        """Re-check a pending stop against current broker and market state.

        Called immediately before any SLTP modification is submitted:

        * the position must still exist under the same ticket;
        * the broker's stop/freeze restrictions are re-read from the symbol
          - they are reported in points, converted into the symbol's own
          price units, and never assumed from an earlier read;
        * a brand-new tick is read and the proposed stop is validated on the
          market side that would execute it: the Bid for a BUY position, the
          Ask for a SELL position.

        ``reason`` names exactly why the current data makes the request
        invalid. A deferred request is never submitted, so the broker's
        existing protective stop is preserved untouched.
        """
        symbol = self._resolved_symbol()
        positions = self._strategy_positions(await self._get_positions())
        fresh: Any | None = None
        for candidate in positions:
            if _get_attr(candidate, "ticket", None) == position_ticket:
                fresh = candidate
        if fresh is None:
            reason = (
                f"position {position_ticket} is no longer open; nothing to modify"
            )
            logger.info("Stop move not submitted: %s", reason)
            self._last_broker_result = f"SLTP not submitted: {reason}"
            return StopMoveValidation(reason=reason)

        mt5 = self.connection.mt5
        try:
            info = await self._get_cached_symbol_info(mt5, symbol)
        except Exception:  # noqa: BLE001 - defer, never send blind
            info = None
        self._adopt_price_metadata(info)
        point_value = _get_attr(info, "point", None) if info is not None else None
        if point_value is None:
            point_value = self._tick_size
        try:
            point_value = float(point_value) if point_value is not None else None
        except (TypeError, ValueError):
            point_value = None

        def _level(attr: str) -> int:
            raw = _get_attr(info, attr, None) if info is not None else None
            try:
                return max(0, int(raw))
            except (TypeError, ValueError):
                return 0

        stops_points = _level("trade_stops_level")
        freeze_points = _level("trade_freeze_level")
        required_gap = 0.0
        freeze_gap = 0.0
        if point_value is not None and point_value > 0:
            required_gap = stops_points * point_value
            freeze_gap = freeze_points * point_value

        # A brand-new tick: a cached quote read while the market is moving is
        # exactly what turns an untouched-but-valid request into ``10016
        # Invalid stops`` between validation and submission.
        tick = await self._read_live_tick()
        bid: float | None
        ask: float | None
        if tick is not None:
            bid, ask = self._market_bid_ask(tick)
        else:
            bid, ask = None, None
        tick_time = _get_attr(tick, "time", None) if tick is not None else None

        def _defer(reason: str) -> StopMoveValidation:
            result = StopMoveValidation(
                position=fresh,
                bid=bid,
                ask=ask,
                tick_time=tick_time,
                stops_points=stops_points,
                freeze_points=freeze_points,
                reason=reason,
            )
            logger.info(
                "Stop move deferred: ticket=%s side=%s desired_sl=%s bid=%s "
                "ask=%s tick_time=%s stops_level=%s freeze_level=%s - %s",
                position_ticket,
                side.upper(),
                target,
                bid,
                ask,
                tick_time,
                stops_points,
                freeze_points,
                reason,
            )
            self._last_broker_result = f"SLTP deferred: {reason}"
            return result

        if bid is None or ask is None:
            return _defer(
                f"no usable Bid/Ask for {symbol} to validate the stop against"
            )

        broker_sl = _get_attr(fresh, "sl", None)
        broker_value: float | None = None
        if broker_sl is not None:
            try:
                broker_value = float(broker_sl)
            except (TypeError, ValueError):
                broker_value = None
        # Reconcile the tracked level with the broker's actual stop so later
        # idempotency and protection checks use the real stored value.
        if broker_value is not None and broker_value > 0:
            self._current_sl = broker_value

        market = bid if side == SIDE_BUY else ask
        # Freeze zone: while the position's current stop sits within the
        # freeze distance of the market, the broker will not process an
        # SLTP modification at all.
        if broker_value is not None and broker_value > 0 and freeze_gap > 0.0:
            freeze_distance = abs(market - broker_value)
            if freeze_distance <= freeze_gap + _SLACK:
                return _defer(
                    f"the broker's current SL {broker_value:g} sits only "
                    f"{freeze_distance:g} price units from the "
                    f"{'Bid' if side == SIDE_BUY else 'Ask'} {market:g}; "
                    f"SLTP modifications are frozen within {freeze_gap:g} "
                    f"(freeze_level={freeze_points} point={point_value})"
                )

        # Side check: a BUY stop closes out at the Bid, so it must sit below
        # the Bid; a SELL stop closes out at the Ask, so it must sit above it.
        market_word = "Bid" if side == SIDE_BUY else "Ask"
        if side == SIDE_BUY:
            gap = float(bid) - float(target)
        else:
            gap = float(target) - float(ask)
        if gap <= _SLACK:
            return _defer(
                f"the proposed SL {target:g} is {gap:g} price units from the "
                f"current {market_word} {market:g}; a {side.upper()} stop must "
                f"sit {'below' if side == SIDE_BUY else 'above'} the "
                f"{market_word}"
            )
        if gap + _SLACK < required_gap:
            return _defer(
                f"the proposed SL {target:g} is only {gap:g} price units from "
                f"the {market_word} {market:g} but the broker requires "
                f"{required_gap:g} (stops_level={stops_points} "
                f"point={point_value})"
            )
        # The proposed stop must be a genuine improvement over the broker's
        # actual stored SL, not just a market-valid level on the right side.
        if broker_value is not None and broker_value > 0:
            improvement_tolerance = self._tolerance()
            if side == SIDE_BUY and target <= broker_value + improvement_tolerance:
                return _defer(
                    f"the proposed SL {target:g} does not improve the broker's "
                    f"current SL {broker_value:g} for a {side.upper()} position"
                )
            if side == SIDE_SELL and target >= broker_value - improvement_tolerance:
                return _defer(
                    f"the proposed SL {target:g} does not improve the broker's "
                    f"current SL {broker_value:g} for a {side.upper()} position"
                )
        return StopMoveValidation(
            position=fresh,
            bid=bid,
            ask=ask,
            tick_time=tick_time,
            stops_points=stops_points,
            freeze_points=freeze_points,
        )

    async def _move_stop(
        self, position: Any, side: str, target_sl: float, *, reason: str
    ) -> bool:
        target = self._norm(target_sl)
        if target is None:
            return False

        # Never resubmit a stop level that the broker already rejected; wait for
        # a new, more protective target before trying again.
        tolerance = self._tolerance()
        if self._rejected_sl_level is not None:
            try:
                if abs(float(self._rejected_sl_level) - float(target)) <= tolerance:
                    return False
            except (TypeError, ValueError):
                pass
        # "current" level. Sync the tracked value first so a stale in-memory
        # level can never trigger a redundant modification.
        broker_sl = _get_attr(position, "sl", None) if position is not None else None
        if broker_sl is not None:
            try:
                broker_sl_value = float(broker_sl)
            except (TypeError, ValueError):
                broker_sl_value = None
            if broker_sl_value is not None and broker_sl_value > 0:
                self._current_sl = broker_sl_value

        tolerance = self._tolerance()
        # Idempotency: if the broker already holds the intended stop (within one
        # tick) there is nothing to modify. Never send a redundant SLTP request.
        if broker_sl is not None:
            try:
                if abs(float(broker_sl) - target) <= tolerance:
                    logger.debug(
                        "Stop already at target; no modification: %s ticket=%s "
                        "sl=%s target=%s",
                        side.upper(),
                        self._position_ticket,
                        broker_sl,
                        target,
                    )
                    self._current_sl = float(broker_sl)
                    return True
            except (TypeError, ValueError):
                pass

        # Never loosen a stop. The broker-side check is re-run against the
        # freshly reconciled broker SL inside _validate_stop_target; here we
        # only honour an explicit retry window so a rejected request is not
        # immediately retried.
        if self._now() < self._sl_retry_at:
            return False

        position_ticket = self._position_ticket
        if position_ticket is None:
            return False

        # Latest-desired-stop handling: never issue concurrent modifications.
        if self._sl_request_in_flight:
            if self._is_more_protective(side, target, self._pending_sl_target):
                self._pending_sl_target = target
                logger.info(
                    "Stop request in flight; stored newer target: %s ticket=%s "
                    "desired=%s pending=%s",
                    side.upper(),
                    position_ticket,
                    target,
                    self._pending_sl_target,
                )
            return False

        # Fresh, current validation immediately before submission: the
        # symbol's stop/freeze restrictions are re-read (they can change
        # server-side), the position must still exist, and the target is
        # checked on the market side that will execute it (Bid for a BUY,
        # Ask for a SELL) against a brand-new tick. An invalid request is
        # never submitted; the broker's existing stop is preserved and the
        # move is deferred to a later scheduler cycle.
        validated = await self._validate_stop_target(position_ticket, side, target)
        if not validated.ok:
            if validated.position is not None:
                # Recoverable: retry on a later cycle rather than repeatedly
                # sending the same rejected request. A non-improving stop is
                # not a transient condition, so it does not earn a retry.
                if "does not improve" not in (validated.reason or ""):
                    self._sl_retry_at = self._now() + _SL_RETRY_SECONDS
                self._last_broker_result = f"SLTP deferred: {validated.reason}"
                self._last_exit_result = (
                    f"break-even stop move deferred: {validated.reason}"
                )
            return False

        self._sl_request_in_flight = True
        self._last_order_attempt = f"SLTP {side.upper()} ticket={position_ticket} target={target}"
        try:
            mt5 = self.connection.mt5
            request = {
                "action": _get_attr(mt5, "TRADE_ACTION_SLTP", 6),
                "symbol": self._resolved_symbol(),
                "position": int(position_ticket),
                "sl": target,
                "tp": _get_attr(validated.position, "tp", 0.0) or 0.0,
                "magic": self.settings.auto_trade_magic_number,
                "comment": _make_comment("AU_M1_T", self._cycle_counter),
            }
            if self._last_sl_request_level != target:
                logger.info(
                    "MT5 SLTP submit: ts=%s profile=%s symbol=%s action=SLTP %s "
                    "position=%s magic=%s sl_before=%s sl_requested=%s tp=%s "
                    "reason=%s bid=%s ask=%s tick_time=%s tick_size=%s "
                    "stops_level=%s freeze_level=%s",
                    _utcnow().isoformat(),
                    getattr(self.settings, "auto_trade_profile", None),
                    self._resolved_symbol(),
                    side.upper(),
                    position_ticket,
                    self.settings.auto_trade_magic_number,
                    self._current_sl,
                    target,
                    _get_attr(validated.position, "tp", 0.0) or 0.0,
                    reason,
                    validated.bid,
                    validated.ask,
                    validated.tick_time,
                    self._tick_size,
                    validated.stops_points,
                    validated.freeze_points,
                )
                self._last_sl_request_level = target

            try:
                _sltp_start_ns = time.perf_counter_ns()
                result = await self.connection.acall(mt5.order_send, request)
                self._profile_stage("sltp_order_send", _sltp_start_ns, side=side, extra=f"retcode={_get_attr(result, 'retcode', None)} target={target}")
            except Exception as exc:  # noqa: BLE001
                self._profile_stage("sltp_order_send", _sltp_start_ns, side=side, extra=f"exception={type(exc).__name__}")
                self._sl_retry_at = self._now() + _SL_RETRY_SECONDS
                self._rejected_sl_level = target
                self._degraded = True
                self._last_broker_result = f"SLTP exception: {type(exc).__name__}: {exc}"
                self._note_error(f"Break-even stop move failed: {exc}")
                return False

            logger.info(
                "MT5 SLTP result: ts=%s profile=%s symbol=%s %s position=%s "                    "retcode=%s comment=%s sl_requested=%s",
                
                _utcnow().isoformat(),
                getattr(self.settings, "auto_trade_profile", None),
                self._resolved_symbol(),
                side.upper(),
                position_ticket,
                _get_attr(result, "retcode", None),
                _get_attr(result, "comment", None),
                target,
            )
            retcode = _get_attr(result, "retcode", None)
            done = _get_attr(mt5, "TRADE_RETCODE_DONE", 10009)
            if result is None or retcode != done:
                comment = _get_attr(result, "comment", None) if result is not None else None
                self._failed_exits += 1
                self._sl_retry_at = self._now() + _SL_RETRY_SECONDS
                self._rejected_sl_level = target
                self._degraded = True
                # Preserve the broker's existing valid SL; reconcile with MT5.
                try:
                    broker_positions = self._strategy_positions(await self._get_positions())
                    for bp in broker_positions:
                        if _get_attr(bp, "ticket", None) == position_ticket:
                            bsl = _get_attr(bp, "sl", None)
                            if bsl is not None:
                                try:
                                    bval = float(bsl)
                                    if bval > 0:
                                        self._current_sl = bval
                                except (TypeError, ValueError):
                                    pass
                            self._position = bp
                except Exception:  # noqa: BLE001
                    pass
                logger.info(
                    "MT5 SLTP rejection reconciled: %s ticket=%s "
                    "broker_stored_sl=%s rejected_request=%s",
                    side.upper(),
                    position_ticket,
                    self._current_sl,
                    target,
                )
                self._last_broker_result = (
                    f"SLTP rejected: retcode={retcode} comment={comment or 'no result'}"
                )
                self._last_exit_result = (
                    f"break-even stop move rejected: retcode={retcode} "
                    f"comment={comment or 'no result'}"
                )
                self._note_error(
                    "Break-even stop move rejected: "
                    f"retcode={retcode} comment={comment or 'no result'}"
                )
                await self._record_trade_event(
                    "sl_modification_failed",
                    price=target,
                    position_id=position_ticket,
                    result_code=retcode,
                    details=comment or "no result",
                )
                return False

            if not await self._confirm_stop_level(position_ticket, side, target):
                self._failed_exits += 1
                self._sl_retry_at = self._now() + _SL_RETRY_SECONDS
                self._note_error(
                    f"Break-even stop move was not confirmed by MT5 for ticket {position_ticket}"
                )
                return False

            old_level = self._current_sl
            # Keep the broker's confirmed level (set by _confirm_stop_level) rather
            # than the requested target, so future idempotency checks use the
            # value actually stored by the terminal.
            if self._current_sl is None:
                self._current_sl = target
            self._rejected_sl_level = None
            self._degraded = False
            self._last_error = None
            self._last_broker_result = f"SLTP done: retcode={retcode} sl={self._current_sl}"
            self._last_exit_result = (
                f"{reason}: {side} ticket {position_ticket} stop {old_level} -> {self._current_sl}"
            )
            self._last_sl_request_level = None
            self._sl_retry_at = 0.0
            logger.info(
                "Break-even stop moved: %s ticket=%s %s -> %s (%s)",
                side.upper(),
                position_ticket,
                old_level,
                target,
                reason,
            )
            await self._persist_state(force=True)
            await self._record_trade_event(
                "sl_modified", price=target, position_id=position_ticket, result_code=0, details=reason
            )
            return True
        finally:
            self._sl_request_in_flight = False
            pending = self._pending_sl_target
            self._pending_sl_target = None
            if pending is not None and self._is_protective_move(side, pending):
                await self._move_stop(position, side, pending, reason=reason)

    async def _confirm_stop_level(self, ticket: int, side: str, target: float) -> bool:
        deadline = self._now() + _CONFIRM_TIMEOUT_SECONDS
        # Tolerate the broker's own normalisation: the stored SL may be rounded
        # to the broker's tick grid, which can differ by up to one tick from the
        # requested value. Accepting the broker's value prevents retry storms.
        tolerance = max(self._tolerance() * 2.0, self._tolerance())
        while True:
            positions = self._strategy_positions(await self._get_positions())
            for position in positions:
                if _get_attr(position, "ticket", None) != ticket:
                    continue
                broker_sl = _get_attr(position, "sl", None)
                if broker_sl is None:
                    continue
                try:
                    broker_value = float(broker_sl)
                except (TypeError, ValueError):
                    continue
                # Accept when the broker's SL matches the target within tolerance,
                # or is already at least as protective as the target.
                acceptable = abs(broker_value - target) <= tolerance
                if side == SIDE_BUY and not acceptable:
                    acceptable = broker_value >= target - tolerance
                if side == SIDE_SELL and not acceptable:
                    acceptable = broker_value <= target + tolerance
                if acceptable:
                    self._position = position
                    self._current_sl = broker_value
                    return True
            if self._now() >= deadline:
                return False
            await self._sleep(_CONFIRM_POLL_SECONDS)

    # ------------------------------------------------------------------
    # Stop-loss confirmation and switching
    # ------------------------------------------------------------------
    @staticmethod
    def _stop_loss_deal(deals: list[Any] | None) -> Any | None:
        if not deals:
            return None
        candidates = [
            deal
            for deal in deals
            if _get_attr(deal, "entry", _DEAL_ENTRY_OUT) == _DEAL_ENTRY_OUT
            and AutoTradingController._is_stop_loss_deal(deal)
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda deal: _get_attr(deal, "time", 0) or 0)[-1]

    async def _handle_closed_position(self, quote: Any) -> None:
        ticket = self._position_ticket
        if ticket is None:
            return
        if self._closed_since is None:
            self._closed_since = self._now()

        deals = await self._history_deals_for(ticket)
        sl_deal = self._stop_loss_deal(deals)
        if sl_deal is not None:
            await self._process_stop_loss_exit(ticket, sl_deal, quote=quote)
            return

        elapsed = self._now() - self._closed_since
        if elapsed < _CLOSED_CONFIRM_TIMEOUT_SECONDS:
            # MT5 may still be publishing the closing deal.
            return

        if not deals:
            # Deal history is temporarily unavailable or not yet published.
            # Keep reconciling and retrying instead of permanently failing or
            # guessing from price action.
            if self._closed_since is None:
                self._closed_since = self._now()
            logger.warning(
                "Position %s is no longer open but no stop-loss deal is available yet; "
                "waiting for a confirmed stop-loss deal",
                ticket,
            )
            return

        self._fail(
            f"Position {ticket} closed without a confirmed stop-loss; "
            "no switch was performed"
        )

    def _price_crossed_stop(self, quote: Any) -> bool:
        if self._current_sl is None or quote is None:
            return False
        tolerance = self._tolerance()
        if self._active_side == SIDE_BUY:
            bid = _get_attr(quote, "bid", None)
            return bid is not None and float(bid) <= self._current_sl + tolerance
        if self._active_side == SIDE_SELL:
            ask = _get_attr(quote, "ask", None)
            return ask is not None and float(ask) >= self._current_sl - tolerance
        return False

    async def _process_stop_loss_exit(
        self,
        ticket: int,
        deal: Any | None,
        *,
        quote: Any,
        during_restore: bool = False,
    ) -> None:
        _cycle_complete_start_ns = time.perf_counter_ns()
        deal_id = self._deal_identifier(deal) if deal is not None else None
        already_processed = (
            deal_id is not None
            and self._last_processed_deal is not None
            and str(self._last_processed_deal) == str(deal_id)
        )
        if already_processed:
            self._clear_active_position()
            return

        if deal_id is not None:
            self._last_processed_deal = deal_id

        side = self._active_side
        cycle_id = self._current_cycle_id
        exit_price = _get_attr(deal, "price", None) if deal is not None else None
        if exit_price in (None, 0.0):
            if quote is not None:
                exit_price = self._favourable_price(quote, side or SIDE_BUY)
            if exit_price in (None, 0.0):
                exit_price = self._current_sl
        profit = _get_attr(deal, "profit", None) if deal is not None else None

        if not during_restore:
            self._completed_cycles += 1
            self._session_completed_cycles += 1

        item = self._find_history_item(cycle_id)
        if item is not None:
            item.status = "closed"
            item.exit_price = exit_price
            item.exit_time = _utcnow()
            item.profit = profit
        self._last_exit_result = (
            f"stop-loss hit for {cycle_id} "
            f"(side={side}, ticket={ticket}, deal={deal_id})"
        )
        logger.info(
            "Stop-loss hit: side=%s ticket=%s deal=%s exit=%s profit=%s -> "
            "Switching phase initiated",
            side,
            ticket,
            deal_id,
            exit_price,
            profit,
        )

        trade_id = f"{self._session_id}-{self._cycle_counter}-{side}" if side else None
        await self._record_trade(
            {
                "trade_id": trade_id,
                "cycle_id": cycle_id,
                "symbol": self._resolved_symbol(),
                "profile": getattr(self.settings, "auto_trade_profile", None),
                "direction": (side or "").upper(),
                "position_id": ticket,
                "status": "closed",
                "exit_filled_at": datetime.now(timezone.utc).isoformat(),
                "actual_exit_price": exit_price,
                "gross_profit": profit,
                "strategy_exit_class": "stop_loss",
                "final_sl_before_exit": self._current_sl,
            }
        )
        await self._record_trade_event(
            "exit_confirmed", trade_id=trade_id, price=exit_price, position_id=ticket, details=f"deal={deal_id}"
        )

        self._clear_active_position()
        self._phase = PHASE_SWITCHING
        self._previous_cycle_complete = True
        self._current_cycle_id = cycle_id

        # Clean up whatever remains of the completed cycle. Only pending
        # orders are touched, never another position's stop-loss.
        await self._cancel_all_pending(reason="cycle completed")
        await self._record_trade_event("switching_started", price=exit_price, position_id=ticket, details=str(deal_id))
        self._profile_stage("cycle_completion", _cycle_complete_start_ns, extra=f"ticket={ticket} deal={deal_id}")
        await self._persist_state(force=True)

    def _clear_active_position(self) -> None:
        self._active_side = None
        self._position_ticket = None
        self._position_type = None
        self._position = None
        self._entry_price = None
        self._entry_time = None
        self._entry_volume = None
        self._current_profit = None
        self._current_sl = None
        self._entry_counted = False
        self._high_water = None
        self._low_water = None
        self._break_even_active = False
        self._break_even_level = None
        self._last_sl_request_level = None
        self._closed_since = None

    # ------------------------------------------------------------------
    # Stop cleanup
    # ------------------------------------------------------------------
    async def _shutdown_cleanup(self) -> None:
        try:
            await self._cancel_all_pending(reason="shutdown")
        except Exception:  # noqa: BLE001
            logger.exception("Failed to cancel pending strategy orders during shutdown")
        if self._position_ticket is not None:
            try:
                if self._worker_state == "FAILED" or self._stop_closes_position():
                    await self._close_position("shutdown")
            except Exception:  # noqa: BLE001
                logger.exception("Failed to close the strategy position during shutdown")
        try:
            await self._persist_state(force=True)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to persist the strategy state during shutdown")

    async def _close_position(self, reason: str) -> bool:
        """Close the active position at market and confirm it with MT5."""
        await self._refresh_mt5_state()
        if self._position_ticket is None:
            return True

        ticket = self._position_ticket
        mt5 = self.connection.mt5
        symbol = self._resolved_symbol()
        side = self._active_side

        for _attempt in range(self.settings.auto_trade_max_retries + 1):
            await self._refresh_mt5_state()
            if self._position_ticket is None:
                return True

            position = self._position
            volume = _get_attr(position, "volume", self._entry_volume) if position else self._entry_volume
            quote = self.monitor.latest_quote()
            if side == SIDE_BUY:
                price = _get_attr(quote, "bid", None) if quote else None
                order_type = _get_attr(mt5, "ORDER_TYPE_SELL", 1)
            else:
                price = _get_attr(quote, "ask", None) if quote else None
                order_type = _get_attr(mt5, "ORDER_TYPE_BUY", 0)
            if price is None:
                self._note_error("No executable price for the close request")
                await self._sleep(1.0)
                continue

            info = await self._get_cached_symbol_info(mt5, symbol)
            request = {
                "action": _get_attr(mt5, "TRADE_ACTION_DEAL", 1),
                "symbol": symbol,
                "volume": volume,
                "type": order_type,
                "position": int(ticket),
                "price": float(price),
                "deviation": self.settings.auto_trade_max_entry_deviation_points,
                "magic": self.settings.auto_trade_magic_number,
                "comment": _make_comment("AU_M1_X", self._cycle_counter or 0),
                "type_time": _get_attr(mt5, "ORDER_TIME_GTC", 0),
                "type_filling": self._filling_mode(mt5, info),
            }
            try:
                result = await self.connection.acall(mt5.order_send, request)
            except Exception as exc:  # noqa: BLE001
                self._note_error(f"Close submission error: {exc}")
                await self._sleep(1.0)
                continue

            retcode = _get_attr(result, "retcode", None)
            done = _get_attr(mt5, "TRADE_RETCODE_DONE", 10009)
            partial = _get_attr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010)
            if result is None or retcode not in (done, partial):
                comment = _get_attr(result, "comment", None) if result is not None else None
                self._note_error(
                    f"Close rejected: retcode={retcode} comment={comment or 'no result'}"
                )
                await self._sleep(1.0)
                continue

            if await self._wait_for_position_absent(ticket):
                logger.info("Position closed: ticket=%s (%s)", ticket, reason)
                self._clear_active_position()
                return True

        self._last_exit_result = f"Failed to close position {ticket}"
        self._note_error(self._last_exit_result)
        return False

    async def _wait_for_position_absent(self, ticket: int) -> bool:
        deadline = self._now() + _CONFIRM_TIMEOUT_SECONDS
        while True:
            positions = self._strategy_positions(await self._get_positions())
            if not any(_get_attr(p, "ticket", None) == ticket for p in positions):
                return True
            if self._now() >= deadline:
                return False
            await self._sleep(_CONFIRM_POLL_SECONDS)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _find_history_item(self, cycle_id: str | None) -> AutoTradingHistoryItem | None:
        if cycle_id is None:
            return None
        for item in reversed(self._history):
            if item.cycle_id == cycle_id:
                return item
        return None

    async def _build_status_unlocked(self) -> AutoTradingStatus:
        terminal_connected = False
        balance = None
        equity = None
        try:
            terminal = await self.connection.acall(self.connection.mt5.terminal_info)
            terminal_connected = bool(terminal and _get_attr(terminal, "connected", False))
        except Exception:  # noqa: BLE001
            pass
        try:
            account = await self.connection.acall(self.connection.mt5.account_info)
            if account is not None:
                balance = _get_attr(account, "balance", None)
                equity = _get_attr(account, "equity", None)
        except Exception:  # noqa: BLE001
            pass

        if self._position_ticket is not None:
            position_status = "open"
        elif self._buy_order_ticket is not None or self._sell_order_ticket is not None:
            position_status = "pending"
        else:
            position_status = "none"

        reported_status = self._compute_reported_status()

        st = AutoTradingStatus(
            status=reported_status,
            symbol=self._resolved_symbol(),
            timeframe=self._strategy_timeframe,
            connection_status="connected" if terminal_connected else "disconnected",
            terminal_connected=terminal_connected,
            trading_enabled=self._worker_state in ("RUNNING", "STARTING"),
            balance=balance,
            equity=equity,
            position_status=position_status,
            position_state=position_status,
            position_ticket=self._position_ticket,
            entry_price=self._entry_price,
            entry_time=self._entry_time,
            current_profit=self._current_profit,
            last_entry_result=self._last_entry_result,
            last_exit_result=self._last_exit_result,
            next_cycle=self._next_cycle,
            completed_cycles=self._completed_cycles,
            session_completed_cycles=self._session_completed_cycles,
            successful_entries=self._successful_entries,
            failed_entries=self._failed_entries,
            failed_exits=self._failed_exits,
            last_error=self._last_error,
            session_id=self._session_id,
            cycle_id=self._current_cycle_id,
            magic_number=self.settings.auto_trade_magic_number,
            strategy_phase=self._phase,
            profile=getattr(self.settings, "auto_trade_profile", None),
            spread_blocked=self._spread_blocked,
            spread_points=(
                self._last_spread_check.spread_points
                if self._last_spread_check is not None
                else None
            ),
            max_spread_points=(
                self._last_spread_check.limit
                if self._last_spread_check is not None
                and self._last_spread_check.limit is not None
                else float(self.settings.auto_trade_max_spread_points)
            ),
            active_side=self._active_side,
            reference_value=self._reference_value,
            buy_entry=self._buy_entry,
            buy_sl=self._buy_sl,
            sell_entry=self._sell_entry,
            sell_sl=self._sell_sl,
            buy_order_ticket=self._buy_order_ticket,
            sell_order_ticket=self._sell_order_ticket,
            highest_favorable_price=self._high_water,
            lowest_favorable_price=self._low_water,
            break_even_active=self._break_even_active,
            break_even_level=self._break_even_level,
            last_processed_deal=self._last_processed_deal,
            previous_cycle_complete=self._previous_cycle_complete,
            worker_heartbeat=self._heartbeat_at,
            heartbeat=self._heartbeat_at,
            last_heartbeat=self._heartbeat_at,
            mt5_connected=terminal_connected,
            mt5_connectivity=terminal_connected,
            mt5_query_ok=self._mt5_query_ok,
            mt5_query_error=self._mt5_query_error,
            pending_order_count=self._pending_order_count,
            pending_orders=self._pending_order_count,
            open_position_count=self._open_position_count,
            open_positions=self._open_position_count,
            last_order_attempt=self._last_order_attempt,
            last_broker_result=self._last_broker_result,
            last_result=self._last_broker_result,
            active_profile=getattr(self.settings, "auto_trade_profile", None),
        )
        self._status = reported_status
        st.sync()
        return st
