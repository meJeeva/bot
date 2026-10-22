"""Automatic M1 trading controller and scheduler."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import Settings
from ..logging_config import get_logger
from ..mt5.connection import MT5Connection, describe_mt5_error
from ..schemas.auto_trading import AutoTradingHistoryItem, AutoTradingHistoryResponse, AutoTradingStatus
from ..services.market_monitor import MarketMonitor

logger = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _broker_now(monitor: MarketMonitor) -> datetime:
    offset = 0
    clock = getattr(monitor, "_clock", None)
    if clock is not None:
        offset = getattr(clock, "offset_seconds", 0) or 0
    return _utcnow() + timedelta(seconds=offset)


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

        self._completed_cycles = 0
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

    async def start(self):
        async with self._lock:
            if self._task is not None and not self._task.done():
                return await self._build_status_unlocked()

            self._stop_requested = False
            self._stop_event.clear()
            self._status = "STARTING"
            self._last_error = None

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
            logger.info("Auto-trading started (session=%s)", self._session_id)

        return await self.status()

    async def stop(self):
        async with self._lock:
            if self._task is None or self._task.done():
                self._status = "STOPPED"
                return await self._build_status_unlocked()
            self._stop_requested = True
            self._stop_event.set()
            self._status = "STOPPING"
            task = self._task

        try:
            await asyncio.wait_for(task, timeout=60.0)
        except Exception as exc:
            logger.warning("Auto-trading stop wait failed: %s", exc)

        async with self._lock:
            if self._position_ticket is not None and self.settings.auto_trade_stop_policy == "close":
                await self._close_position("stop requested")
            if self._position_ticket is None:
                self._status = "STOPPED"
            else:
                self._status = "ERROR"
            self._task = None

        return await self.status()

    async def status(self):
        async with self._lock:
            return await self._build_status_unlocked()

    async def history(self):
        async with self._lock:
            items = list(self._history)
            return AutoTradingHistoryResponse(items=items, history=items, count=len(items))

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
        if self._position_ticket is not None:
            raise RuntimeError("A strategy position is already open")

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

    async def _run(self):
        try:
            while not self._stop_requested:
                await self._reconcile_position_unlocked()

                if self._position_ticket is not None:
                    await self._close_position("reconciliation")
                    if self._position_ticket is not None:
                        await asyncio.sleep(1.0)
                        continue

                if self._completed_cycles >= self.settings.auto_trade_max_cycles:
                    self._last_error = "Maximum cycles per session reached"
                    self._stop_requested = True
                    break

                loss = await self._session_loss()
                if loss is not None and loss >= self.settings.auto_trade_max_daily_loss:
                    self._last_error = "Maximum daily loss reached"
                    self._stop_requested = True
                    break

                self._next_cycle = self._next_minute_boundary()
                await self._sleep_until(self._next_cycle, self._stop_event)
                if self._stop_requested:
                    break

                await self._enter_cycle()

                if self._position_ticket is not None:
                    entry_time = self._entry_time or _utcnow()
                    exit_deadline = entry_time + timedelta(seconds=60 - self.settings.auto_trade_exit_seconds_before_minute_end)
                    await self._sleep_until(exit_deadline, self._stop_event)
                    if self._stop_requested:
                        break
                    await self._exit_cycle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            self._status = "ERROR"
            logger.exception("Auto-trading loop failed")
        finally:
            if self._position_ticket is not None:
                await self._close_position("shutdown")
            async with self._lock:
                if self._status != "ERROR":
                    self._status = "STOPPED"
                self._task = None
                self._next_cycle = None

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

    def _next_minute_boundary(self):
        now = _broker_now(self.monitor)
        boundary = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        if (boundary - now).total_seconds() < 0.5:
            boundary = boundary + timedelta(minutes=1)
        return boundary

    async def _sleep_until(self, target, event):
        while not event.is_set():
            now = _broker_now(self.monitor)
            remaining = (target - now).total_seconds()
            if remaining <= 0:
                return
            await asyncio.sleep(min(remaining, 0.5))

    async def _enter_cycle(self):
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
                    self._last_entry_result = "entry ambiguous but strategy position exists"
                    self._last_error = self._last_entry_result
                    item.status = "ambiguous"
                    item.error = self._last_entry_result
                    logger.warning("%s", self._last_entry_result)
                    return
                self._failed_entries += 1
                self._last_entry_result = "entry submission returned no result"
                self._last_error = self._last_entry_result
                item.status = "failed"
                item.error = self._last_entry_result
                return

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
                return

            for _ in range(6):
                await asyncio.sleep(0.5)
                await self._reconcile_position_unlocked()
                if self._position_ticket is not None:
                    break
            if self._position_ticket is None:
                self._failed_entries += 1
                self._last_entry_result = "entry reported done but no strategy position found"
                self._last_error = self._last_entry_result
                item.status = "ambiguous"
                item.error = self._last_entry_result
                return

            self._successful_entries += 1
            self._last_entry_result = f"entry filled ticket {self._position_ticket}"
            item.status = "filled"
            item.entry_price = self._entry_price
            item.entry_time = self._entry_time
            item.volume = self._entry_volume
            logger.info("Entry filled: cycle=%s ticket=%s", cycle_id, self._position_ticket)
        except Exception as exc:
            self._failed_entries += 1
            self._last_entry_result = f"entry failed: {exc}"
            self._last_error = self._last_entry_result
            item.status = "error"
            item.error = self._last_entry_result
            logger.exception("Entry failed")
        finally:
            self._entry_in_progress = False

    async def _preflight_entry(self):
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
            "comment": "AU_M1_B%d" % self._cycle_counter,
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

    async def _exit_cycle(self):
        self._exit_in_progress = True
        cycle_id = self._current_cycle_id
        item = self._find_history_item(cycle_id)
        try:
            await self._close_position("scheduled exit")
            if self._position_ticket is None:
                self._completed_cycles += 1
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

    async def _close_position(self, reason):
        await self._reconcile_position_unlocked()
        if self._position_ticket is None:
            return

        ticket = self._position_ticket
        volume = self._entry_volume
        mt5 = self.connection.mt5
        symbol = self._resolved_symbol()

        for attempt in range(self.settings.auto_trade_max_retries + 1):
            await self._reconcile_position_unlocked()
            if self._position_ticket is None:
                return

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
                await asyncio.sleep(1.0)
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
                "comment": "AU_M1_C%d" % (self._cycle_counter or 0),
                "type_time": getattr(mt5, "ORDER_TIME_GTC", 0),
                "type_filling": self._filling_mode(mt5, info),
            }

            try:
                result = await self.connection.acall(mt5.order_send, request)
            except Exception as exc:
                self._last_error = f"Exit submission error: {exc}"
                await asyncio.sleep(1.0)
                continue

            retcode = getattr(result, "retcode", None)
            done_code = getattr(mt5, "TRADE_RETCODE_DONE", 10009)
            if retcode != done_code:
                self._last_error = f"Exit rejected: {getattr(result, 'comment', retcode)}"
                await asyncio.sleep(1.0)
                continue

            for _ in range(6):
                await asyncio.sleep(0.5)
                await self._reconcile_position_unlocked()
                if self._position_ticket is not None:
                    break
            if self._position_ticket is None:
                self._current_profit = None
                self._entry_volume = None
                return

        self._failed_exits += 1
        self._last_exit_result = f"Failed to close position {ticket}"
        self._last_error = self._last_exit_result

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
            timeframe="M1",
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
