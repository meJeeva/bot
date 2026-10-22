"""Automatic BUY-only trading controller (5-second entry cycle).

The strategy is purely time based: one BUY, hold for a fixed duration from the
confirmed fill, close that position, then wait until the entry cadence allows
the next BUY. All scheduling uses a monotonic clock so wall-clock adjustments
cannot stretch or compress the holding period or the entry interval.

Only one strategy position may be open at a time. If an exit cannot be
confirmed the scheduler keeps tracking that position and skips entries rather
than opening an overlapping trade.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import Settings
from ..logging_config import get_logger
from ..mt5.connection import MT5Connection, describe_mt5_error
from ..schemas.auto_trading import AutoTradingHistoryItem, AutoTradingHistoryResponse, AutoTradingStatus
from ..services.market_monitor import MarketMonitor

logger = get_logger(__name__)

# Granularity of a scheduler wait. Small enough that a stop request is honoured
# promptly, large enough that the loop does not spin.
_WAIT_SLICE_SECONDS = 0.1
# How often MT5 is reconciled while waiting for an order to be confirmed.
_CONFIRM_POLL_SECONDS = 0.1
# Upper bound for MT5 to report a submitted entry or a completed exit.
_CONFIRM_TIMEOUT_SECONDS = 5.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_comment(prefix: str, counter: int) -> str:
    """Generate a valid MT5 order comment.

    MT5 comments must be 31 characters or less. Format: prefix + counter.
    Examples: AU_M1_B1, AU_M1_B99, AU_M1_C1
    """
    comment = f"{prefix}{counter}"
    if len(comment) > 31:
        # Truncate counter digits if needed (should never happen with reasonable cycle counts)
        comment = comment[:31]
    return comment


class AutoTradingController:
    def __init__(self, settings: Settings, connection: MT5Connection, monitor: MarketMonitor, store: Any = None) -> None:
        self.settings = settings
        self.connection = connection
        self.monitor = monitor
        self.store = store

        self._lock = asyncio.Lock()
        self._task = None
        self._stop_requested = False
        self._stop_event = asyncio.Event()

        self._status = "STOPPED"
        self._session_id = None
        self._cycle_counter = 0
        self._current_cycle_id = None

        self._position_ticket = None
        self._entry_price = None
        self._entry_time = None
        self._entry_volume = None
        self._current_profit = None
        # Monotonic timestamp of the confirmed fill for the position opened by
        # the current session. ``None`` for a position adopted from elsewhere.
        self._entry_filled_monotonic = None

        # Lifetime statistic, preserved across sessions.
        self._completed_cycles = 0
        # Per-session counter that gates AUTO_TRADE_MAX_CYCLES.
        self._session_completed_cycles = 0
        self._successful_entries = 0
        self._failed_entries = 0
        self._failed_exits = 0

        self._last_entry_result = None
        self._last_exit_result = None
        self._last_error = None

        self._next_cycle = None
        self._start_balance = None

        self._history = []

        self._entry_in_progress = False
        self._exit_in_progress = False

    # ------------------------------------------------------------------
    # Clock and waiting primitives
    # ------------------------------------------------------------------
    def _now(self) -> float:
        """Monotonic seconds. Never wall-clock: only elapsed time matters."""
        return time.monotonic()

    async def _sleep(self, seconds: float) -> None:
        """Single sleep primitive, isolated so tests can drive a virtual clock."""
        await asyncio.sleep(max(0.0, seconds))

    async def _wait_until(self, deadline: float) -> None:
        """Wait for a monotonic deadline, waking immediately on stop."""
        while not self._stop_event.is_set():
            remaining = deadline - self._now()
            if remaining <= 0:
                return
            await self._sleep(min(remaining, _WAIT_SLICE_SECONDS))

    def _publish_next_cycle(self, deadline: float) -> None:
        """Express a monotonic deadline as a UTC timestamp for the status API."""
        self._next_cycle = _utcnow() + timedelta(seconds=max(0.0, deadline - self._now()))

    async def _wait_for_position(self, present: bool) -> bool:
        """Reconcile until a strategy position is present/absent, or time out."""
        deadline = self._now() + _CONFIRM_TIMEOUT_SECONDS
        while True:
            await self._reconcile_position_unlocked()
            if (self._position_ticket is not None) is present:
                return True
            if self._now() >= deadline:
                return False
            await self._sleep(_CONFIRM_POLL_SECONDS)

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
            self._status = "STARTING"
            self._last_error = None
            # Every Start opens a fresh session: the cycle limit applies to
            # this session only, and any adopted position starts with an
            # unknown fill time (closed before the first entry).
            self._session_completed_cycles = 0
            self._entry_filled_monotonic = None

            try:
                await self._preflight()
            except Exception as exc:
                self._status = "ERROR"
                self._last_error = str(exc)
                logger.error("Auto-trading preflight failed: %s", exc)
                return await self._build_status_unlocked()

            self._session_id = str(uuid.uuid4())
            self._start_balance = await self._account_balance()
            self._status = "RUNNING"
            self._task = asyncio.create_task(self._run(), name="auto-trading")
            logger.info(
                "Auto-trading started (session=%s, entry_interval=%ss, holding=%ss)",
                self._session_id,
                self.settings.auto_trade_entry_interval_seconds,
                self.settings.auto_trade_holding_duration_seconds,
            )

        return await self.status()

    async def stop(self):
        async with self._lock:
            task = self._task
            # Prevent any further entry immediately, then let the loop unwind.
            self._stop_requested = True
            self._stop_event.set()
            if task is not None and not task.done():
                self._status = "STOPPING"

        if task is not None and not task.done():
            try:
                await asyncio.wait_for(task, timeout=60.0)
            except Exception as exc:
                logger.warning("Auto-trading stop wait failed: %s", exc)
            if not task.done():
                async with self._lock:
                    self._status = "ERROR"
                    self._last_error = "Auto-trading loop did not stop in time"
                return await self.status()

        async with self._lock:
            # Report from live MT5 state, never from what the scheduler intended.
            await self._reconcile_position_unlocked()
            close_policy = self._stop_closes_position()
            if self._position_ticket is not None and close_policy:
                await self._close_position("stop requested")
                await self._reconcile_position_unlocked()

            if self._position_ticket is None:
                # Only report a flat book once MT5 confirms it.
                self._status = "STOPPED"
            elif close_policy:
                self._status = "ERROR"
                self._last_error = (
                    f"Strategy position {self._position_ticket} is still open after Stop"
                )
            else:
                # 'leave' is deliberate: keep the position and say so.
                self._status = "STOPPED"
                self._last_exit_result = (
                    f"stop policy 'leave': strategy position {self._position_ticket} left open"
                )
            self._task = None

        return await self.status()

    def _stop_closes_position(self) -> bool:
        """Whether Stop must flatten the strategy position.

        ``close`` is the safe default; anything other than an explicit
        ``leave`` (including an unreadable value) closes.
        """
        policy = str(self.settings.auto_trade_stop_policy or "close").strip().lower()
        return policy != "leave"

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
    async def _preflight(self):
        if not await self.connection.acall(self.connection.is_connected):
            raise RuntimeError("MT5 terminal is not connected")

        mt5 = self.connection.mt5
        terminal = await self.connection.acall(mt5.terminal_info)
        if terminal is None:
            raise RuntimeError("MT5 terminal info is unavailable")
        if not getattr(terminal, "trade_allowed", True):
            raise RuntimeError("MT5 terminal AutoTrading is disabled")

        account = await self.connection.acall(mt5.account_info)
        if account is None:
            raise RuntimeError("MT5 account info is unavailable")

        symbol = self._resolved_symbol()
        if symbol is None:
            raise RuntimeError("Trading symbol is not resolved")

        quote = self.monitor.latest_quote()
        if quote is None or getattr(quote, "is_stale", False):
            raise RuntimeError("Market prices are unavailable or stale")

        volume = self.settings.auto_trade_volume
        info = await self.connection.acall(mt5.symbol_info, symbol)
        if info is None:
            raise RuntimeError("Symbol info is unavailable")
        vmin = getattr(info, "volume_min", None)
        vmax = getattr(info, "volume_max", None)
        vstep = getattr(info, "volume_step", None)
        if vmin is not None and volume < vmin:
            raise RuntimeError("Volume below broker minimum")
        if vmax is not None and volume > vmax:
            raise RuntimeError("Volume exceeds broker maximum")
        if vstep:
            base = vmin or 0.0
            steps = round((volume - base) / vstep)
            if abs(steps * vstep + base - volume) > 1e-9:
                raise RuntimeError("Volume does not match broker step")

        spread = getattr(quote, "spread_points", None)
        if spread is not None and spread > self.settings.auto_trade_max_spread_points:
            raise RuntimeError("Spread exceeds maximum")

        await self._reconcile_position_unlocked()
        # An already-open strategy position is reconciled and closed by the
        # run loop before any new entry is attempted.

    def _resolved_symbol(self):
        status = self.monitor.symbol_status
        return getattr(status, "resolved", None) or getattr(status, "requested", None)

    async def _account_balance(self):
        try:
            account = await self.connection.acall(self.connection.mt5.account_info)
            return getattr(account, "balance", None) if account else None
        except Exception:
            return None

    async def _account_info(self):
        try:
            return await self.connection.acall(self.connection.mt5.account_info)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Scheduler
    # ------------------------------------------------------------------
    async def _run(self):
        """BUY at T, request the exit at T+holding, next BUY at T+interval.

        The next entry deadline is anchored on the previous *confirmed* fill,
        never on the close, so the intended gap between close and next entry is
        (interval - holding). When the loop is late it never catches up: exactly
        one entry follows, and the cadence restarts from that fill.
        """
        interval = float(self.settings.auto_trade_entry_interval_seconds)
        next_entry_at = None
        try:
            while not self._stop_requested:
                await self._reconcile_position_unlocked()

                if self._position_ticket is not None:
                    await self._hold_and_exit()
                    if self._position_ticket is not None:
                        # The exit is not confirmed: keep tracking this position
                        # and skip entries. Never open an overlapping trade.
                        self._last_error = "Strategy position still open; entries skipped"
                        await self._sleep(1.0)
                        continue

                if self._session_completed_cycles >= self.settings.auto_trade_max_cycles:
                    self._last_error = "Maximum cycles per session reached"
                    self._stop_requested = True
                    break

                loss = await self._session_loss()
                if loss is not None and loss >= self.settings.auto_trade_max_daily_loss:
                    self._last_error = "Maximum daily loss reached"
                    self._stop_requested = True
                    break

                if next_entry_at is not None:
                    self._publish_next_cycle(next_entry_at)
                    await self._wait_until(next_entry_at)
                    if self._stop_requested:
                        break
                    late_by = self._now() - next_entry_at
                    if late_by > interval:
                        logger.warning(
                            "Entry cycle delayed by %.1fs; missed cycles are skipped, not caught up",
                            late_by,
                        )

                filled_at = await self._enter_cycle()
                next_entry_at = (
                    filled_at if filled_at is not None else self._now()
                ) + interval
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            self._status = "ERROR"
            logger.exception("Auto-trading loop failed")
        finally:
            # A requested Stop follows the configured policy. A crash or an
            # internal error still gets the emergency close, so a failure can
            # never abandon a strategy position.
            if self._position_ticket is not None:
                if self._status == "ERROR" or self._stop_closes_position():
                    await self._close_position("shutdown")
            async with self._lock:
                if self._status != "ERROR":
                    self._status = "STOPPED"
                self._task = None
                self._next_cycle = None

    async def _hold_and_exit(self):
        """Honour the holding duration, then request and verify the close."""
        filled_at = self._entry_filled_monotonic
        if filled_at is None:
            # Position adopted from a previous session: its fill time in this
            # process is unknown, so close it before opening anything new.
            # This is not a completed cycle of the current session.
            await self._close_position("reconciliation")
            return

        exit_at = filled_at + float(self.settings.auto_trade_holding_duration_seconds)
        self._publish_next_cycle(exit_at)
        await self._wait_until(exit_at)
        if self._stop_requested or self._now() < exit_at:
            return
        await self._exit_cycle()

    async def _session_loss(self):
        if self._start_balance is None:
            return None
        account = await self._account_info()
        if account is None:
            return None
        equity = getattr(account, "equity", None)
        if equity is None:
            return None
        return self._start_balance - equity

    # ------------------------------------------------------------------
    # Entry
    # ------------------------------------------------------------------
    async def _enter_cycle(self):
        """Submit one BUY and return the monotonic time its fill was confirmed."""
        self._entry_in_progress = True
        self._cycle_counter += 1
        cycle_id = f"{self._session_id}-{self._cycle_counter}"
        self._current_cycle_id = cycle_id
        item = AutoTradingHistoryItem(cycle_id=cycle_id, symbol=self._resolved_symbol(), status="pending")
        self._history.append(item)

        try:
            await self._preflight_entry()
            result = await self._submit_entry(cycle_id)
            if result is None:
                if self._position_ticket is not None:
                    self._entry_filled_monotonic = self._now()
                    self._last_entry_result = "entry ambiguous but strategy position exists"
                    self._last_error = self._last_entry_result
                    item.status = "ambiguous"
                    item.error = self._last_entry_result
                    logger.warning("%s", self._last_entry_result)
                    return self._entry_filled_monotonic
                self._failed_entries += 1
                self._last_entry_result = "entry submission returned no result"
                self._last_error = self._last_entry_result
                item.status = "failed"
                item.error = self._last_entry_result
                return None

            retcode = getattr(result, "retcode", None)
            done_code = getattr(self.connection.mt5, "TRADE_RETCODE_DONE", 10009)
            partial_code = getattr(self.connection.mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010)
            if retcode not in (done_code, partial_code):
                msg = getattr(result, "comment", None) or f"retcode={retcode}"
                self._failed_entries += 1
                self._last_entry_result = f"entry rejected: {msg}"
                self._last_error = self._last_entry_result
                item.status = "rejected"
                item.error = self._last_entry_result
                logger.warning("Entry rejected: retcode=%s comment=%s", retcode, getattr(result, "comment", None))
                return None

            if not await self._wait_for_position(True):
                self._failed_entries += 1
                self._last_entry_result = "entry reported done but no strategy position found"
                self._last_error = self._last_entry_result
                item.status = "ambiguous"
                item.error = self._last_entry_result
                return None

            # The holding timer starts here: from the confirmed fill, not from
            # the order-submission time.
            filled_at = self._now()
            self._entry_filled_monotonic = filled_at
            self._successful_entries += 1
            self._last_entry_result = f"entry filled ticket {self._position_ticket}"
            item.status = "filled"
            item.entry_price = self._entry_price
            item.entry_time = self._entry_time
            item.volume = self._entry_volume
            logger.info("Entry filled: cycle=%s ticket=%s", cycle_id, self._position_ticket)
            return filled_at
        except Exception as exc:
            if self._position_ticket is not None and self._entry_filled_monotonic is None:
                # The order did reach the market: hold it like any other fill
                # instead of closing it immediately or re-submitting.
                self._entry_filled_monotonic = self._now()
                self._last_entry_result = f"entry ambiguous: {exc}"
                self._last_error = self._last_entry_result
                item.status = "ambiguous"
                item.error = self._last_entry_result
                logger.warning("%s", self._last_entry_result)
                return self._entry_filled_monotonic
            if self._stop_requested:
                # Stop raced the entry: the order was never submitted.
                item.status = "cancelled"
                return None
            self._failed_entries += 1
            self._last_entry_result = f"entry failed: {exc}"
            self._last_error = self._last_entry_result
            item.status = "error"
            item.error = self._last_entry_result
            logger.exception("Entry failed")
            return None
        finally:
            self._entry_in_progress = False

    async def _preflight_entry(self):
        if self._stop_requested:
            # Stop may arrive while an earlier wait or call was in flight.
            raise RuntimeError("Stop requested; entry cancelled")
        if not await self.connection.acall(self.connection.is_connected):
            raise RuntimeError("MT5 terminal is not connected")
        terminal = await self.connection.acall(self.connection.mt5.terminal_info)
        if terminal is None or not getattr(terminal, "trade_allowed", True):
            raise RuntimeError("MT5 AutoTrading is disabled")
        symbol = self._resolved_symbol()
        if symbol is None:
            raise RuntimeError("Symbol not resolved")
        quote = self.monitor.latest_quote()
        if quote is None or getattr(quote, "is_stale", False):
            raise RuntimeError("Prices unavailable or stale")
        spread = getattr(quote, "spread_points", None)
        if spread is not None and spread > self.settings.auto_trade_max_spread_points:
            raise RuntimeError("Spread too wide")
        await self._reconcile_position_unlocked()
        if self._position_ticket is not None:
            raise RuntimeError("Previous strategy position still open")

    async def _submit_entry(self, cycle_id):
        mt5 = self.connection.mt5
        symbol = self._resolved_symbol()
        quote = self.monitor.latest_quote()
        price = getattr(quote, "ask", None) if quote else None
        if price is None:
            raise RuntimeError("No ask price")

        info = await self.connection.acall(mt5.symbol_info, symbol)
        volume = self.settings.auto_trade_volume
        filling = self._filling_mode(mt5, info)

        request = {
            "action": getattr(mt5, "TRADE_ACTION_DEAL", 1),
            "symbol": symbol,
            "volume": volume,
            "type": getattr(mt5, "ORDER_TYPE_BUY", 0),
            "price": price,
            "deviation": self.settings.auto_trade_max_entry_deviation_points,
            "magic": self.settings.auto_trade_magic_number,
            "comment": _make_comment("AU_M1_B", self._cycle_counter),
            "type_time": getattr(mt5, "ORDER_TIME_GTC", 0),
            "type_filling": filling,
        }
        logger.info("Submitting entry: %s", request)
        try:
            result = await self.connection.acall(mt5.order_send, request)
        except Exception as exc:  # noqa: BLE001
            logger.exception("order_send raised an exception: %s", exc)
            try:
                last_err = await self.connection.acall(mt5.last_error)
            except Exception:  # noqa: BLE001
                last_err = None
            self._last_error = "order_send raised: %s; last_error=%s" % (exc, describe_mt5_error(last_err))
            await self._reconcile_position_unlocked()
            if self._position_ticket is not None:
                self._last_entry_result = "entry ambiguous but position found after timeout"
                return None
            raise

        if result is None:
            try:
                last_err = await self.connection.acall(mt5.last_error)
            except Exception:  # noqa: BLE001
                last_err = None
            logger.error("order_send returned None; mt5.last_error=%s", describe_mt5_error(last_err))
            self._last_error = "order_send returned None; %s" % describe_mt5_error(last_err)
            await self._reconcile_position_unlocked()
            if self._position_ticket is not None:
                self._last_entry_result = "entry ambiguous but position found after None result"
                return None
            return None

        logger.info(
            "order_send result: retcode=%s comment=%s order=%s deal=%s volume=%s price=%s",
            getattr(result, "retcode", None),
            getattr(result, "comment", None),
            getattr(result, "order", None),
            getattr(result, "deal", None),
            getattr(result, "volume", None),
            getattr(result, "price", None),
        )
        return result

    # ------------------------------------------------------------------
    # Exit
    # ------------------------------------------------------------------
    async def _exit_cycle(self):
        self._exit_in_progress = True
        cycle_id = self._current_cycle_id
        item = self._find_history_item(cycle_id)
        try:
            await self._close_position("scheduled exit")
            if self._position_ticket is None:
                self._completed_cycles += 1
                self._session_completed_cycles += 1
                self._last_exit_result = f"exit filled for {cycle_id}"
                if item is not None:
                    item.status = "closed"
                    item.exit_time = _utcnow()
                logger.info("Exit filled: cycle=%s", cycle_id)
            else:
                self._failed_exits += 1
                self._last_exit_result = f"exit failed for {cycle_id}"
                self._last_error = self._last_exit_result
                if item is not None:
                    item.status = "exit_failed"
                    item.error = self._last_exit_result
        except Exception as exc:
            self._failed_exits += 1
            self._last_exit_result = f"exit error: {exc}"
            self._last_error = self._last_exit_result
            if item is not None:
                item.status = "exit_error"
                item.error = self._last_exit_result
        finally:
            self._exit_in_progress = False

    async def _close_position(self, reason) -> bool:
        """Request the close and confirm it against MT5.

        Returns ``True`` only when MT5 reports no strategy position left; a
        submitted request is never treated as a closed position on its own.
        """
        await self._reconcile_position_unlocked()
        if self._position_ticket is None:
            return True

        ticket = self._position_ticket
        volume = self._entry_volume
        mt5 = self.connection.mt5
        symbol = self._resolved_symbol()

        for attempt in range(self.settings.auto_trade_max_retries + 1):
            await self._reconcile_position_unlocked()
            if self._position_ticket is None:
                return True

            pos_volume = volume
            positions = await self._get_positions()
            for p in positions:
                if getattr(p, "ticket", None) == ticket:
                    pos_volume = getattr(p, "volume", pos_volume)
                    break

            quote = self.monitor.latest_quote()
            price = getattr(quote, "bid", None) if quote else None
            if price is None:
                self._last_error = "No bid price for exit"
                await self._sleep(1.0)
                continue

            info = await self.connection.acall(mt5.symbol_info, symbol)
            request = {
                "action": getattr(mt5, "TRADE_ACTION_DEAL", 1),
                "symbol": symbol,
                "volume": pos_volume,
                "type": getattr(mt5, "ORDER_TYPE_SELL", 1),
                "position": ticket,
                "price": price,
                "deviation": self.settings.auto_trade_max_entry_deviation_points,
                "magic": self.settings.auto_trade_magic_number,
                "comment": _make_comment("AU_M1_C", self._cycle_counter or 0),
                "type_time": getattr(mt5, "ORDER_TIME_GTC", 0),
                "type_filling": self._filling_mode(mt5, info),
            }

            try:
                result = await self.connection.acall(mt5.order_send, request)
            except Exception as exc:
                self._last_error = f"Exit submission error: {exc}"
                await self._sleep(1.0)
                continue

            if result is None:
                try:
                    last_err = await self.connection.acall(mt5.last_error)
                except Exception:  # noqa: BLE001
                    last_err = None
                logger.error("Exit order_send returned None; mt5.last_error=%s", describe_mt5_error(last_err))
                self._last_error = f"Exit order_send returned None; {describe_mt5_error(last_err)}"
                await self._sleep(1.0)
                continue

            retcode = getattr(result, "retcode", None)
            done_code = getattr(mt5, "TRADE_RETCODE_DONE", 10009)
            if retcode != done_code:
                self._last_error = f"Exit rejected: {getattr(result, 'comment', retcode)}"
                logger.warning("Exit rejected: retcode=%s comment=%s", retcode, getattr(result, "comment", None))
                await self._sleep(1.0)
                continue

            # A submitted request is not a closed position: confirm with MT5.
            if await self._wait_for_position(False):
                self._current_profit = None
                self._entry_volume = None
                self._entry_filled_monotonic = None
                return True

        self._last_exit_result = f"Failed to close position {ticket}"
        self._last_error = self._last_exit_result
        return False

    async def _get_positions(self):
        mt5 = self.connection.mt5
        symbol = self._resolved_symbol()
        try:
            positions = await self.connection.acall(mt5.positions_get, symbol=symbol)
        except Exception:
            positions = None
        if positions is None:
            try:
                positions = await self.connection.acall(mt5.positions_get)
            except Exception:
                positions = []
        return list(positions or [])

    async def _reconcile_position_unlocked(self):
        try:
            positions = await self._get_positions()
            magic = self.settings.auto_trade_magic_number
            strategy = [p for p in positions if getattr(p, "magic", None) == magic]
            if strategy:
                p = strategy[-1]
                self._position_ticket = getattr(p, "ticket", None)
                self._entry_price = getattr(p, "price_open", None)
                self._entry_volume = getattr(p, "volume", None)
                self._current_profit = getattr(p, "profit", None)
                raw_time = getattr(p, "time", None)
                if raw_time:
                    offset = 0
                    clock = getattr(self.monitor, "_clock", None)
                    if clock is not None:
                        offset = getattr(clock, "offset_seconds", 0) or 0
                    self._entry_time = datetime.fromtimestamp(raw_time - offset, tz=timezone.utc)
            else:
                if self._position_ticket is not None:
                    self._position_ticket = None
                    self._entry_price = None
                    self._entry_volume = None
                    self._current_profit = None
                    self._entry_time = None
                    self._entry_filled_monotonic = None
        except Exception as exc:
            self._last_error = f"Reconciliation failed: {exc}"

    async def _reconcile_position(self):
        async with self._lock:
            await self._reconcile_position_unlocked()

    def _filling_mode(self, mt5, info):
        filling_mode = getattr(info, "filling_mode", None) if info is not None else None
        ioc = getattr(mt5, "ORDER_FILLING_IOC", 1)
        fok = getattr(mt5, "ORDER_FILLING_FOK", 0)
        if filling_mode is not None:
            if filling_mode & 2:
                return ioc
            if filling_mode & 1:
                return fok
        return fok

    def _find_history_item(self, cycle_id):
        if cycle_id is None:
            return None
        for item in reversed(self._history):
            if item.cycle_id == cycle_id:
                return item
        return None

    async def _build_status_unlocked(self):
        terminal_connected = False
        balance = None
        equity = None
        try:
            terminal = await self.connection.acall(self.connection.mt5.terminal_info)
            terminal_connected = bool(terminal and getattr(terminal, "connected", False))
        except Exception:
            pass
        try:
            account = await self.connection.acall(self.connection.mt5.account_info)
            if account is not None:
                balance = getattr(account, "balance", None)
                equity = getattr(account, "equity", None)
        except Exception:
            pass

        await self._reconcile_position_unlocked()

        position_status = "open" if self._position_ticket is not None else "none"

        from ..schemas.auto_trading import AutoTradingStatus

        st = AutoTradingStatus(
            status=self._status,
            symbol=self._resolved_symbol(),
            timeframe="5s",
            connection_status="connected" if terminal_connected else "disconnected",
            terminal_connected=terminal_connected,
            trading_enabled=self._status in ("RUNNING", "STARTING"),
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
        )
        st.sync()
        return st
