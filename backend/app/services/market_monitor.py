"""Continuous market-data monitoring service.

The monitor is a single background asyncio task that:

* keeps the MT5 connection alive and reconnects with capped backoff,
* resolves the broker's gold symbol once and re-checks it after reconnects,
* polls the newest tick at a configurable interval,
* keeps a rolling candle cache for all seven timeframes,
* publishes a :class:`~app.schemas.market.MarketSnapshot` to every WebSocket
  subscriber when something actually changed,
* reports **stale** data instead of continuing to present it as live.

It runs completely independently of HTTP traffic: the API only ever reads the
cached snapshot, so a slow or disconnected terminal cannot block a request.

Every MetaTrader call is dispatched through
:meth:`app.mt5.connection.MT5Connection.acall`, which serialises it onto a
dedicated worker thread - the event loop is never blocked and shared connection
state cannot be corrupted by concurrent requests.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import Settings
from ..logging_config import get_logger
from ..mt5.connection import MT5Connection, MT5UnavailableError
from ..mt5.market_data import (
    MarketDataError,
    ServerClock,
    read_candles,
    read_quote,
)
from ..mt5.symbols import (
    SymbolDiscoveryResult,
    SymbolProperties,
    SymbolResolutionStatus,
    discover_symbol,
    ensure_symbol_selected,
)
from ..mt5.timeframes import TIMEFRAME_ORDER, get_timeframe, normalize_timeframe
from ..schemas.market import (
    Candle,
    CandleSeries,
    MarketSnapshot,
    Quote,
    TimeframeSummary,
)
from ..schemas.status import (
    ConnectionState,
    DataStatus,
    MT5Status,
    SymbolInfo,
    SymbolStatus,
)
from ..storage import StatusStore

logger = get_logger(__name__)

# How often symbol discovery is retried while unresolved.
_SYMBOL_RETRY_SECONDS = 30
# Consecutive poll failures before the connection is treated as lost.
_FAILURE_THRESHOLD = 3


def _utcnow() -> datetime:
    """Indirection point so tests can control time."""
    return datetime.now(timezone.utc)


class MarketMonitor:
    """Polls MT5, caches market data and fans snapshots out to subscribers."""

    def __init__(
        self,
        connection: MT5Connection,
        settings: Settings,
        *,
        store: StatusStore | None = None,
        clock: ServerClock | None = None,
        started_at: datetime | None = None,
    ) -> None:
        self._connection = connection
        self._settings = settings
        self._store = store
        self._clock = clock or ServerClock()
        self._started_at = started_at or _utcnow()

        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

        self._symbol_status = SymbolStatus(
            requested=settings.mt5_symbol,
            resolution="pending",
            message="Symbol has not been resolved yet.",
        )
        self._symbol_properties: SymbolProperties | None = None

        self._connection_status: MT5Status | None = None

        self._quote: Quote | None = None
        self._candle_cache: dict[str, CandleSeries] = {}
        self._candle_fetched_at: dict[str, datetime] = {}

        self._subscribers: set[asyncio.Queue[MarketSnapshot]] = set()
        self._sequence = 0
        self._data_status = DataStatus.UNAVAILABLE
        self._last_error: str | None = None
        self._last_market_update: datetime | None = None

        self._last_emitted_key: tuple[Any, ...] | None = None
        self._last_emitted_at: datetime | None = None
        self._consecutive_failures = 0
        self._symbol_checked_at: datetime | None = None
        self._last_quote_store_at: datetime | None = None
        self._last_status_store: tuple[Any, ...] | None = None

    # ==================================================================
    # Lifecycle
    # ==================================================================
    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start the monitoring loop. Duplicate calls are ignored."""
        if self.running:
            logger.warning("Market monitor is already running; start() ignored.")
            return

        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="market-monitor")
        logger.info(
            "Market monitor started (interval=%sms, symbol=%s)",
            self._settings.poll_interval_ms,
            self._settings.mt5_symbol,
        )

    async def stop(self) -> None:
        """Stop the monitoring loop cleanly."""
        self._stopping.set()
        task = self._task
        self._task = None
        if task is None:
            return

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        logger.info("Market monitor stopped.")

    # ==================================================================
    # Subscriptions
    # ==================================================================
    def subscribe(self) -> asyncio.Queue[MarketSnapshot]:
        """Register a WebSocket client and return its bounded queue.

        The queue is bounded so a slow client cannot grow memory without limit;
        on overflow the oldest frame is discarded in favour of the newest.
        """
        queue: asyncio.Queue[MarketSnapshot] = asyncio.Queue(
            maxsize=self._settings.ws_max_queue
        )
        self._subscribers.add(queue)
        logger.info(
            "WebSocket client subscribed (%s active)", len(self._subscribers)
        )
        return queue

    def unsubscribe(self, queue: asyncio.Queue[MarketSnapshot]) -> None:
        self._subscribers.discard(queue)
        logger.info(
            "WebSocket client unsubscribed (%s active)", len(self._subscribers)
        )

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    # ==================================================================
    # Read-only views used by the API
    # ==================================================================
    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def connection(self) -> MT5Connection:
        return self._connection

    @property
    def started_at(self) -> datetime:
        return self._started_at

    @property
    def data_status(self) -> DataStatus:
        return self.effective_data_status()

    def effective_data_status(self, now: datetime | None = None) -> DataStatus:
        """Freshness of what the API would serve *right now*.

        The stored status reflects the last poll; between polls the only thing
        that changes is the age of the tick. A quote that has aged past the
        threshold therefore degrades the status to ``stale`` - it is never
        upgraded, so a poll that failed cannot look healthy again just because
        the retained price is still young.
        """
        quote = self._quote
        if quote is None:
            return self._data_status
        if self._with_current_age(quote, now or _utcnow()).is_stale:
            return DataStatus.STALE
        return self._data_status

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def last_market_update(self) -> datetime | None:
        """When market data last changed, or None if nothing has arrived yet."""
        return self._last_market_update

    @property
    def sequence(self) -> int:
        return self._sequence

    @property
    def symbol_status(self) -> SymbolStatus:
        return self._symbol_status

    def latest_quote(self) -> Quote | None:
        """Most recent usable tick, with age/freshness recomputed now."""
        if self._quote is None:
            return None
        return self._with_current_age(self._quote, _utcnow())

    def cached_connection_status(self) -> MT5Status | None:
        """Last observed connection status. Performs no MT5 calls."""
        return self._connection_status

    def stamp_server_clock(self, status: MT5Status) -> MT5Status:
        """Attach the measured broker clock offset to a status object.

        The offset is discovered from ticks, so the connection manager cannot
        know it itself; the monitor is where the two meet.
        """
        if self._clock.measured:
            status.server_time_offset_seconds = self._clock.offset_seconds
        return status

    async def connection_status(self) -> MT5Status:
        status = await self._connection.acall(self._connection.build_status_sync)
        return self.stamp_server_clock(status)

    def build_snapshot_sync(self) -> MarketSnapshot:
        """Build a snapshot from cached state without touching MT5."""
        now = _utcnow()
        connection_status = self._connection_status
        if connection_status is None:
            connection_status = self._safe_default_status()

        quote = self._with_current_age(self._quote, now) if self._quote else None

        timeframes: dict[str, TimeframeSummary] = {}
        for name in TIMEFRAME_ORDER:
            timeframes[name] = self._summarize(name, now)

        quote_age = quote.age_seconds if quote is not None else None

        return MarketSnapshot(
            sequence=self._sequence,
            generated_at=now,
            connection=connection_status,
            symbol=self._symbol_status,
            quote=quote,
            data_status=self.effective_data_status(now),
            last_market_update=self._last_market_update,
            quote_age_seconds=quote_age,
            timeframes=timeframes,
            last_error=self._last_error,
            trading_enabled=False,
            read_only=True,
        )

    async def build_snapshot(self) -> MarketSnapshot:
        """Snapshot with a freshly read connection status."""
        try:
            self._connection_status = self.stamp_server_clock(
                await self._connection.acall(self._connection.build_status_sync)
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Could not refresh connection status: %s", exc)
        return self.build_snapshot_sync()

    def candle_series(self, timeframe: str) -> CandleSeries | None:
        return self._candle_cache.get(normalize_timeframe(timeframe))

    async def get_candles(self, timeframe: str, limit: int) -> CandleSeries:
        """Return history for ``timeframe``, fetching it when needed."""
        name = normalize_timeframe(timeframe)
        series = await self._refresh_timeframe(name, limit)
        return self._trim(series, limit) if len(series.candles) > limit else series

    # ==================================================================
    # Monitoring loop
    # ==================================================================
    async def _run(self) -> None:
        interval = self._settings.poll_interval_seconds
        try:
            await self._ensure_symbol()
            while not self._stopping.is_set():
                started = time.monotonic()
                try:
                    await self._poll_once()
                    self._consecutive_failures = 0
                except asyncio.CancelledError:
                    raise
                except MT5UnavailableError as exc:
                    self._note_failure(str(exc))
                    self._consecutive_failures = _FAILURE_THRESHOLD
                except Exception as exc:  # noqa: BLE001 - loop must survive
                    self._note_failure(f"{type(exc).__name__}: {exc}")
                    logger.exception("Unexpected error in market monitor loop")

                elapsed = time.monotonic() - started
                # Never sleep less than a floor, so a fast poll cannot spin the CPU.
                await asyncio.sleep(max(0.05, interval - elapsed))
        except asyncio.CancelledError:
            logger.debug("Market monitor task cancelled.")
            raise
        finally:
            logger.debug("Market monitor loop exited.")

    async def _poll_once(self) -> None:
        connection = self._connection

        # --- connection health -----------------------------------------
        if not await connection.acall(connection.is_connected):
            recovered = await connection.acall(connection.reconnect_sync)
            if not recovered:
                self._data_status = (
                    DataStatus.STALE if self._quote else DataStatus.UNAVAILABLE
                )
                self._connection_status = self.stamp_server_clock(
                    await connection.acall(connection.build_status_sync)
                )
                await self._publish(force=False)
                return
            logger.info("MT5 connection recovered; re-validating symbol.")
            await self._ensure_symbol(force=True)

        self._connection_status = self.stamp_server_clock(
            await connection.acall(connection.build_status_sync)
        )

        # --- symbol ----------------------------------------------------
        if (
            self._symbol_status.resolution != "resolved"
            and self._should_retry_symbol()
        ):
            await self._ensure_symbol(force=True)

        if self._symbol_status.resolution != "resolved" or not self._symbol_properties:
            self._data_status = (
                DataStatus.STALE if self._quote else DataStatus.UNAVAILABLE
            )
            await self._publish(force=False)
            return

        # --- tick ------------------------------------------------------
        await self._read_and_store_quote()

        # --- one overdue timeframe per tick (bounded CPU use) ----------
        await self._refresh_next_timeframe()

        await self._persist_status()
        await self._publish(force=False)

    async def _read_and_store_quote(self) -> Quote | None:
        """Read the newest tick and fold it into the cached state.

        Also measures the broker server-clock offset, which every candle
        timestamp conversion depends on.
        """
        properties = self._symbol_properties
        if properties is None:
            return None

        connection = self._connection
        quote: Quote | None
        try:
            mt5 = connection.mt5
            quote = await connection.acall(
                read_quote,
                mt5,
                properties.name,
                point=properties.point,
                digits=properties.digits,
                tick_size=properties.tick_size,
                tick_value=properties.tick_value,
                stale_threshold_seconds=self._settings.stale_tick_threshold_seconds,
                clock=self._clock,
                now_utc=_utcnow(),
            )
        except MT5UnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._note_failure(f"Tick read failed: {exc}")
            quote = None

        now = _utcnow()
        if quote is None:
            self._note_failure("No usable tick was returned by the terminal.")
            self._data_status = (
                DataStatus.STALE if self._quote else DataStatus.UNAVAILABLE
            )
            return None

        self._quote = quote
        self._last_market_update = now
        self._last_error = None
        self._data_status = DataStatus.STALE if quote.is_stale else DataStatus.LIVE
        await connection.acall(connection.mark_market_data, now)
        await self._persist_quote(quote)
        return quote

    # ------------------------------------------------------------------
    async def _ensure_symbol(self, force: bool = False) -> None:
        """Resolve and select the trading symbol."""
        self._symbol_checked_at = _utcnow()
        connection = self._connection

        try:
            mt5 = connection.mt5
            result: SymbolDiscoveryResult = await connection.acall(
                discover_symbol,
                mt5,
                self._settings.mt5_symbol,
                self._settings.symbol_candidates,
                strict=self._settings.mt5_symbol_strict,
            )
        except MT5UnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._note_failure(f"Symbol discovery failed: {exc}")
            self._symbol_status = SymbolStatus(
                requested=self._settings.mt5_symbol,
                resolution="pending",
                message=f"Symbol discovery failed: {exc}",
            )
            return

        if result.status is SymbolResolutionStatus.RESOLVED and result.properties:
            previous_name = (
                self._symbol_properties.name if self._symbol_properties else None
            )

            if self._settings.select_symbol_in_market_watch:
                selected = await connection.acall(
                    ensure_symbol_selected, connection.mt5, result.properties.name
                )
                if not selected:
                    result.message += (
                        " The symbol could not be added to Market Watch; ticks may "
                        "be unavailable."
                    )

            self._symbol_properties = result.properties
            self._symbol_status = self._symbol_status_from_result(result)

            if force or result.properties.name != previous_name:
                self._candle_cache.clear()
                self._candle_fetched_at.clear()

            logger.info(
                "Trading symbol resolved: %s (%s)", result.properties.name, result.message
            )
            return

        self._symbol_properties = None
        self._symbol_status = self._symbol_status_from_result(result)
        self._note_failure(result.message)

    def _symbol_status_from_result(self, result: SymbolDiscoveryResult) -> SymbolStatus:
        info: SymbolInfo | None = None
        if result.properties is not None:
            properties = result.properties
            info = SymbolInfo(
                name=properties.name,
                digits=properties.digits,
                point=properties.point,
                tick_size=properties.tick_size,
                tick_value=properties.tick_value,
                broker_spread_points=properties.broker_spread_points,
                currency_base=properties.currency_base,
                currency_profit=properties.currency_profit,
            )
        return SymbolStatus(
            requested=result.requested_symbol,
            resolved=result.symbol,
            resolution=result.status.value,
            matched_by=result.matched_by.value if result.matched_by else None,
            modifier=result.modifier or None,
            message=result.message,
            candidates=list(result.candidates),
            requires_configuration=result.requires_configuration,
            info=info,
        )

    def _should_retry_symbol(self) -> bool:
        if self._symbol_checked_at is None:
            return True
        return (_utcnow() - self._symbol_checked_at).total_seconds() >= _SYMBOL_RETRY_SECONDS

    # ------------------------------------------------------------------
    async def _refresh_next_timeframe(self) -> None:
        """Refresh at most one overdue timeframe per poll tick."""
        overdue: list[str] = []
        now = _utcnow()
        for name in TIMEFRAME_ORDER:
            fetched = self._candle_fetched_at.get(name)
            if fetched is None:
                overdue.append(name)
                continue
            age = (now - fetched).total_seconds()
            if age >= self._settings.candle_refresh_seconds:
                overdue.append(name)

        if not overdue:
            return

        target = overdue[0]
        try:
            await self._refresh_timeframe(target, self._settings.candle_limit)
        except MarketDataError as exc:
            logger.warning("Candle refresh failed for %s: %s", target, exc)
            series = self._candle_cache.get(target)
            if series is not None:
                self._candle_cache[target] = series.model_copy(
                    update={"warnings": [*series.warnings, exc.message][-5:]}
                )
        except Exception as exc:  # noqa: BLE001 - must not kill the loop
            logger.warning("Unexpected candle refresh error for %s: %s", target, exc)

    async def _refresh_timeframe(self, name: str, limit: int) -> CandleSeries:
        """Fetch and cache a candle series when it is missing or overdue."""
        name = normalize_timeframe(name)
        limit = max(1, int(limit))
        spec = get_timeframe(name)

        cached = self._candle_cache.get(name)
        fetched_at = self._candle_fetched_at.get(name)
        now = _utcnow()

        if cached is not None and fetched_at is not None:
            fresh = (
                now - fetched_at
            ).total_seconds() < self._settings.candle_refresh_seconds
            covers = cached.requested_limit >= limit or cached.incomplete_history
            if fresh and covers:
                return cached

        properties = self._symbol_properties
        if properties is None:
            raise MarketDataError(
                "symbol_unresolved",
                "Cannot read candles: no trading symbol has been resolved yet.",
            )

        # Bar timestamps are broker-local, so the offset must be measured before
        # any bar can be classified as complete. If this request arrives before
        # the monitor's first tick, measure it now - otherwise an offset of 0
        # would make every bar look like it is still forming.
        if not self._clock.measured:
            await self._read_and_store_quote()

        connection = self._connection
        fetch_limit = max(limit, self._settings.candle_limit)

        try:
            mt5 = connection.mt5
            candles: list[Candle] = await connection.acall(
                read_candles,
                mt5,
                properties.name,
                name,
                fetch_limit,
                offset_seconds=self._clock.offset_seconds,
                now_utc=now,
            )
        except MarketDataError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise MarketDataError(
                "candle_read_failed", f"Candle read failed for {name}: {exc}"
            ) from exc

        warnings: list[str] = []
        if len(candles) < limit:
            warnings.append(
                f"Only {len(candles)} of {limit} requested {name} bars are "
                "available from the terminal."
            )
        if not self._clock.measured:
            warnings.append(
                "The broker server clock offset could not be measured (no tick "
                "is available), so bar completion times are unreliable."
            )

        closed_candles = [candle for candle in candles if candle.is_closed]
        series = CandleSeries(
            symbol=properties.name,
            timeframe=name,
            timeframe_seconds=spec.seconds,
            requested_limit=fetch_limit,
            count=len(candles),
            candles=candles,
            latest_candle=candles[-1] if candles else None,
            latest_closed_candle=closed_candles[-1] if closed_candles else None,
            server_time_offset_seconds=self._clock.offset_seconds,
            time_convention="broker_server_local",
            incomplete_history=len(candles) < limit,
            warnings=warnings,
            generated_at=now,
        )

        self._candle_cache[name] = series
        self._candle_fetched_at[name] = now
        logger.debug(
            "Cached %s %s candles (offset=%ss)",
            len(candles),
            name,
            self._clock.offset_seconds,
        )
        return series

    # ------------------------------------------------------------------
    def _summarize(self, name: str, now: datetime) -> TimeframeSummary:
        series = self._candle_cache.get(name)
        spec = get_timeframe(name)
        if series is None:
            return TimeframeSummary(
                timeframe=name,
                seconds=spec.seconds,
                error="No data cached yet.",
            )

        closed, forming = self._split_closed(series.candles, spec.seconds, now)
        return TimeframeSummary(
            timeframe=name,
            seconds=spec.seconds,
            latest_closed=closed,
            forming=forming,
            candle_count=len(series.candles),
            last_updated=self._candle_fetched_at.get(name),
            error=series.warnings[-1] if series.warnings else None,
        )

    @staticmethod
    def _split_closed(
        candles: list[Candle], seconds: int, now: datetime
    ) -> tuple[Candle | None, Candle | None]:
        """Recompute completion using the current clock.

        A bar is complete once its full duration has elapsed, regardless of
        when the series was fetched. This is what keeps a forming bar from
        being presented as finished (or a finished bar from looking live).
        """
        if not candles:
            return None, None

        closed: Candle | None = None
        for candle in reversed(candles):
            if candle.open_time_utc + timedelta(seconds=seconds) <= now:
                closed = candle
                break

        forming: Candle | None = None
        last = candles[-1]
        if last.open_time_utc + timedelta(seconds=seconds) > now:
            forming = last

        return closed, forming

    def _with_current_age(self, quote: Quote, now: datetime) -> Quote:
        """Recompute age and freshness against the current clock.

        The stored tick instant never moves, so a frozen feed keeps ageing and
        eventually reports as stale rather than staying "live" forever.
        """
        if quote.tick_time_utc is None:
            return quote.model_copy(
                update={"age_seconds": None, "freshness": "unknown", "is_stale": True}
            )
        age = max(0.0, (now - quote.tick_time_utc).total_seconds())
        is_stale = age > self._settings.stale_tick_threshold_seconds
        return quote.model_copy(
            update={
                "age_seconds": age,
                "is_stale": is_stale,
                "freshness": "stale" if is_stale else "live",
            }
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    async def _persist_quote(self, quote: Quote) -> None:
        if self._store is None or not self._store.enabled:
            return
        now = _utcnow()

        # Snapshot every poll would flood the file; sample once a second.
        if (
            self._last_quote_store_at is not None
            and (now - self._last_quote_store_at).total_seconds() < 1.0
        ):
            return
        self._last_quote_store_at = now
        try:
            await asyncio.to_thread(self._store.record_quote, quote)
        except Exception as exc:  # noqa: BLE001 - persistence must never break polling
            logger.warning("Could not persist a market snapshot: %s", exc)

    async def _persist_status(self) -> None:
        if self._store is None or not self._store.enabled:
            return
        status = self._connection_status
        if status is None:
            return
        key = (
            status.state.value,
            status.last_connection_error,
            self._symbol_status.resolved,
        )
        if key == self._last_status_store:
            return
        self._last_status_store = key
        try:
            await asyncio.to_thread(
                self._store.record_connection_event,
                status,
                symbol=self._symbol_status.resolved,
            )
        except Exception as exc:  # noqa: BLE001 - persistence must never break polling
            logger.warning("Could not persist a connection event: %s", exc)

    # ------------------------------------------------------------------
    # Fan-out
    # ------------------------------------------------------------------
    async def _publish(self, *, force: bool) -> None:
        now = _utcnow()
        key = self._emission_key(now)
        due = (
            self._last_emitted_at is None
            or (now - self._last_emitted_at).total_seconds()
            >= self._settings.ws_push_interval_seconds
        )

        if not force and key == self._last_emitted_key and not due:
            return

        self._sequence += 1
        self._last_emitted_key = key
        self._last_emitted_at = now

        if not self._subscribers:
            return

        snapshot = self.build_snapshot_sync()
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(snapshot)
            except asyncio.QueueFull:
                # Drop the oldest frame so the newest always reaches the client.
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(snapshot)
                logger.debug("Dropped a queued frame for a slow WebSocket client.")

    def _emission_key(self, now: datetime) -> tuple[Any, ...]:
        quote = self._quote
        return (
            self._data_status.value,
            self._symbol_status.resolution,
            self._symbol_status.resolved,
            None if quote is None else quote.bid,
            None if quote is None else quote.ask,
            None if quote is None else quote.tick_time_utc,
            quote.is_stale if quote is not None else None,
            self._symbol_options_key(),
        )

    def _symbol_options_key(self) -> tuple[str, ...]:
        return tuple(self._symbol_status.candidates)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _note_failure(self, message: str) -> None:
        self._last_error = message
        self._consecutive_failures += 1
        if self._consecutive_failures == 1:
            logger.warning("Market monitor issue: %s", message)
        if self._consecutive_failures >= _FAILURE_THRESHOLD:
            self._consecutive_failures = 0
            self._connection.register_disconnect(message)

    def _safe_default_status(self) -> MT5Status:
        return self.stamp_server_clock(
            MT5Status(
                state=ConnectionState.DISCONNECTED,
                last_connection_error=self._last_error,
                read_only=True,
                trading_enabled=False,
            )
        )

    def _trim(self, series: CandleSeries, limit: int) -> CandleSeries:
        candles = series.candles[-limit:]
        closed_candles = [candle for candle in candles if candle.is_closed]
        return series.model_copy(
            update={
                "candles": candles,
                "count": len(candles),
                "requested_limit": limit,
                "latest_candle": candles[-1] if candles else None,
                "latest_closed_candle": closed_candles[-1] if closed_candles else None,
            }
        )
