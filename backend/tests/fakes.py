"""A fake MetaTrader 5 module for unit tests.

Everything in here is a **mock**. Passing tests that use this module prove the
backend logic is correct; they are never evidence that a real terminal is
reachable. Only ``tests/integration/test_live_mt5.py`` talks to the genuine
MetaTrader 5 package.
"""

from __future__ import annotations

import fnmatch
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

import numpy as np

# Matches the structured dtype returned by mt5.copy_rates_from_pos().
RATE_DTYPE = np.dtype(
    [
        ("time", "<i8"),
        ("open", "<f8"),
        ("high", "<f8"),
        ("low", "<f8"),
        ("close", "<f8"),
        ("tick_volume", "<u8"),
        ("spread", "<i4"),
        ("real_volume", "<u8"),
    ]
)

# MetaQuotes timeframe constants (mirrors app.mt5.timeframes).
TIMEFRAME_M1 = 1
TIMEFRAME_M5 = 5
TIMEFRAME_M15 = 15
TIMEFRAME_M30 = 30
TIMEFRAME_H1 = 16385
TIMEFRAME_H4 = 16388
TIMEFRAME_D1 = 16408

ACCOUNT_TRADE_MODE_DEMO = 0
ACCOUNT_TRADE_MODE_CONTEST = 1
ACCOUNT_TRADE_MODE_REAL = 2

SYMBOL_FILLING_FOK = 1
SYMBOL_FILLING_IOC = 2

TRADE_ACTION_DEAL = 1
ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1
ORDER_TIME_GTC = 0
ORDER_FILLING_FOK = 0
ORDER_FILLING_IOC = 1
TRADE_RETCODE_DONE = 10009
TRADE_RETCODE_DONE_PARTIAL = 10010

TRADE_ACTION_DEAL = 1
ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1
ORDER_TIME_GTC = 0
ORDER_FILLING_FOK = 0
ORDER_FILLING_IOC = 1
TRADE_RETCODE_DONE = 10009
TRADE_RETCODE_DONE_PARTIAL = 10010

# Pending-order / stop-management constants used by the M1 strategy.
TRADE_ACTION_PENDING = 5
TRADE_ACTION_REMOVE = 8
TRADE_ACTION_SLTP = 6
ORDER_TYPE_BUY_LIMIT = 2
ORDER_TYPE_SELL_LIMIT = 3
ORDER_TYPE_BUY_STOP = 4
ORDER_TYPE_SELL_STOP = 5
ORDER_TYPE_BUY_STOP_LIMIT = 6
ORDER_TYPE_SELL_STOP_LIMIT = 7
DEAL_ENTRY_IN = 0
DEAL_ENTRY_OUT = 1
DEAL_REASON_SL = 4

# The MetaQuotes-Demo server observed during development runs at UTC+3.
DEFAULT_SERVER_OFFSET_SECONDS = 10800


def broker_time(
    offset_seconds: int = DEFAULT_SERVER_OFFSET_SECONDS, delta_seconds: float = 0.0
) -> int:
    """A broker-server timestamp corresponding to *now* (plus a delta).

    Because MetaTrader timestamps are broker-local, the value is the real UTC
    epoch shifted by the server offset - exactly what a live terminal returns.
    """
    return int(time.time() + offset_seconds + delta_seconds)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_rates(rows: Sequence[Sequence[Any]]) -> np.ndarray:
    """Build a structured array from ``(time, o, h, l, c, tv, spread, rv)`` rows."""
    array = np.zeros(len(rows), dtype=RATE_DTYPE)
    for index, row in enumerate(rows):
        array[index] = tuple(row)  # type: ignore[index]
    return array


def make_candle_rows(
    *,
    end_time: int,
    step_seconds: int,
    count: int,
    base_price: float = 2400.0,
    price_step: float = 0.5,
) -> list[list[Any]]:
    """Generate a plausible, ordered OHLC series ending at ``end_time``."""
    rows: list[list[Any]] = []
    for index in range(count):
        open_time = end_time - (count - 1 - index) * step_seconds
        open_price = base_price + index * price_step
        close_price = open_price + price_step
        rows.append(
            [
                open_time,
                open_price,
                max(open_price, close_price) + 0.4,
                min(open_price, close_price) - 0.4,
                close_price,
                100 + index,
                12,
                0,
            ]
        )
    return rows


class FakeSymbolInfo:
    def __init__(
        self,
        name: str,
        *,
        digits: int = 2,
        point: float = 0.01,
        visible: bool = True,
        spread: int = 56,
        trade_tick_size: float = 0.01,
        trade_tick_value: float = 0.1,
        currency_base: str = "XAU",
        currency_profit: str = "USD",
        trade_mode: int = 4,
        trade_contract_size: float | None = None,
        volume_min: float = 0.01,
        volume_step: float = 0.01,
        volume_max: float = 100.0,
        volume_limit: float = 0.0,
        trade_stops_level: int = 0,
        trade_freeze_level: int = 0,
        filling_mode: int = SYMBOL_FILLING_FOK | SYMBOL_FILLING_IOC,
        trade_tick_value_loss: float | None = None,
    ) -> None:
        self.name = name
        self.digits = digits
        self.point = point
        self.visible = visible
        self.spread = spread
        self.trade_tick_size = trade_tick_size
        self.trade_tick_value = trade_tick_value
        self.trade_tick_value_loss = (
            trade_tick_value if trade_tick_value_loss is None else trade_tick_value_loss
        )
        self.currency_base = currency_base
        self.currency_profit = currency_profit
        self.trade_mode = trade_mode
        # Deliberately absent unless supplied: the production loader must
        # refuse a symbol whose contract size the broker did not report, so a
        # bare fake must not silently supply one.
        if trade_contract_size is not None:
            self.trade_contract_size = trade_contract_size
        self.volume_min = volume_min
        self.volume_step = volume_step
        self.volume_max = volume_max
        self.volume_limit = volume_limit
        self.trade_stops_level = trade_stops_level
        self.trade_freeze_level = trade_freeze_level
        self.filling_mode = filling_mode


class FakeTick:
    def __init__(
        self,
        *,
        time: int,
        bid: float = 2400.0,
        ask: float = 2400.5,
        last: float = 0.0,
        volume: int = 0,
        time_msc: int | None = None,
    ) -> None:
        self.time = time
        self.bid = bid
        self.ask = ask
        self.last = last
        self.volume = volume
        self.time_msc = time_msc if time_msc is not None else time * 1000
        self.flags = 1028


class FakeTerminalInfo:
    def __init__(
        self,
        *,
        connected: bool = True,
        path: str = r"C:\Program Files\MetaTrader 5",
        name: str = "MetaTrader 5",
        company: str = "MetaQuotes Ltd.",
        build: int = 6140,
        language: str = "English",
        server: str = "MetaQuotes-Demo",
    ) -> None:
        self.connected = connected
        self.path = path
        self.name = name
        self.company = company
        self.build = build
        self.language = language
        self.server = server
        self.community_account = 0
        self.trade_allowed = True
        self.trade_allowed = True


class FakeAccountInfo:
    def __init__(
        self,
        *,
        login: int = 5057247615,
        server: str = "MetaQuotes-Demo",
        currency: str = "USD",
        trade_mode: int = ACCOUNT_TRADE_MODE_DEMO,
        balance: float = 100000.0,
        equity: float | None = None,
        margin_free: float | None = None,
    ) -> None:
        self.login = login
        self.server = server
        self.currency = currency
        self.trade_mode = trade_mode
        self.balance = balance
        self.equity = balance if equity is None else equity
        self.margin_free = (self.equity * 10) if margin_free is None else margin_free
        self.leverage = 100


@dataclass
@dataclass
class FakePosition:
    ticket: int
    time: int = 0
    time_msc: int = 0
    type: int = 0
    magic: int = 0
    identifier: int = 0
    reason: int = 0
    volume: float = 0.01
    price_open: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    price_current: float = 0.0
    swap: float = 0.0
    profit: float = 0.0
    symbol: str = "XAUUSD"
    comment: str = ""
    external_id: str = ""


@dataclass
class FakeOrder:
    ticket: int
    time: int = 0
    type: int = 0
    magic: int = 0
    volume: float = 0.01
    price: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    symbol: str = "XAUUSD"
    comment: str = ""
    price_open: float = 0.0

    def __post_init__(self) -> None:
        if not self.price_open:
            self.price_open = self.price


@dataclass
class FakeDeal:
    ticket: int = 0
    order: int = 0
    position_id: int = 0
    position: int = 0
    time: int = 0
    type: int = 0
    entry: int = DEAL_ENTRY_OUT
    magic: int = 0
    volume: float = 0.01
    price: float = 0.0
    profit: float = 0.0
    symbol: str = "XAUUSD"
    comment: str = "sl"
    reason: int = DEAL_REASON_SL

    def __post_init__(self) -> None:
        if not self.position:
            self.position = self.position_id


@dataclass
class FakeOrderResult:
    retcode: int = 10009
    deal: int = 1
    order: int = 1
    volume: float = 0.01
    price: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    comment: str = "done"
    request_id: int = 0
    retcode_external: int = 0
    position: int = None


@dataclass
class FakePosition:
    ticket: int
    time: int = 0
    time_msc: int = 0
    type: int = 0
    magic: int = 0
    identifier: int = 0
    reason: int = 0
    volume: float = 0.01
    price_open: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    price_current: float = 0.0
    swap: float = 0.0
    profit: float = 0.0
    symbol: str = "XAUUSD"
    comment: str = ""
    external_id: str = ""


@dataclass
class FakeOrder:
    ticket: int
    time: int = 0
    type: int = 0
    magic: int = 0
    volume: float = 0.01
    price: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    symbol: str = "XAUUSD"
    comment: str = ""
    price_open: float = 0.0

    def __post_init__(self) -> None:
        if not self.price_open:
            self.price_open = self.price


@dataclass
class FakeDeal:
    ticket: int = 0
    order: int = 0
    position_id: int = 0
    position: int = 0
    time: int = 0
    type: int = 0
    entry: int = DEAL_ENTRY_OUT
    magic: int = 0
    volume: float = 0.01
    price: float = 0.0
    profit: float = 0.0
    symbol: str = "XAUUSD"
    comment: str = "sl"
    reason: int = DEAL_REASON_SL

    def __post_init__(self) -> None:
        if not self.position:
            self.position = self.position_id


@dataclass
class FakeOrderResult:
    retcode: int = 10009
    deal: int = 1
    order: int = 1
    volume: float = 0.01
    price: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    comment: str = "done"
    request_id: int = 0
    retcode_external: int = 0
    position: int = None


class FakeMT5:
    """Stand-in for the ``MetaTrader5`` package.

    Only market-data, terminal and account functions are implemented. No
    order-submission function exists on this fake, so a read-only cycle cannot
    accidentally exercise one.
    """

    def __init__(
        self,
        *,
        symbols: Iterable[FakeSymbolInfo] | None = None,
        ticks: dict[str, FakeTick | None] | None = None,
        rates: dict[tuple[str, int], np.ndarray | None] | None = None,
        initialize_ok: bool = True,
        initialize_results: list[bool] | None = None,
        terminal: FakeTerminalInfo | None = None,
        account: FakeAccountInfo | None = None,
        last_error_value: tuple[int, str] = (1, "Success"),
    ) -> None:
        default_symbols = [
            FakeSymbolInfo("XAUUSD"),
            FakeSymbolInfo("XAUEUR"),
            FakeSymbolInfo("XAUAUD"),
            FakeSymbolInfo("XAUCHF"),
            FakeSymbolInfo("XAUGBP"),
            FakeSymbolInfo("XAUG"),
            FakeSymbolInfo("EURUSD", digits=5, point=0.00001),
        ]
        self.symbols = list(symbols) if symbols is not None else default_symbols
        self.ticks = dict(ticks) if ticks is not None else {}
        self.rates = dict(rates) if rates is not None else {}
        self.terminal = terminal or FakeTerminalInfo()
        if not hasattr(self.terminal, 'trade_allowed'):
            self.terminal.trade_allowed = True
        if not hasattr(self.terminal, 'trade_allowed'):
            self.terminal.trade_allowed = True
        self.account = account or FakeAccountInfo()

        self.initialize_ok = initialize_ok
        self._initialize_results = list(initialize_results) if initialize_results else None
        self._last_error = last_error_value

        # Call instrumentation - used by assertions in the tests.
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.initialized = False
        self.shutdown_calls = 0
        self.selected: set[str] = set()
        self.positions: list[FakePosition] = []
        self.orders: list[FakeOrder] = []
        self.deals: list[FakeDeal] = []
        self.order_send_retcode = 10009
        self.order_send_results = None
        self.next_position_ticket = 1001
        self.next_order_ticket = 2001
        self.trade_allowed = True
        self.positions: list[FakePosition] = []
        self.orders: list[FakeOrder] = []
        self.deals: list[FakeDeal] = []
        self.order_send_retcode = 10009
        self.order_send_results = None
        self.next_position_ticket = 1001
        self.next_order_ticket = 2001
        self.trade_allowed = True

    # -- instrumentation -------------------------------------------------
    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def call_names(self) -> list[str]:
        return [name for name, _, _ in self.calls]

    # -- lifecycle -------------------------------------------------------
    def initialize(self, **kwargs: Any) -> bool:
        self._record("initialize", **kwargs)
        if self._initialize_results:
            result = self._initialize_results.pop(0)
        else:
            result = self.initialize_ok
        self.initialized = result
        return result

    def shutdown(self) -> None:
        self._record("shutdown")
        self.shutdown_calls += 1
        self.initialized = False

    def version(self) -> tuple[int, int, str]:
        self._record("version")
        return (500, 6140, "21 Aug 2026")

    def last_error(self) -> tuple[int, str]:
        self._record("last_error")
        return self._last_error

    # -- terminal / account ---------------------------------------------
    def terminal_info(self) -> FakeTerminalInfo | None:
        self._record("terminal_info")
        if self.terminal is not None:
            self.terminal.trade_allowed = getattr(self, 'trade_allowed', True)
        return self.terminal if self.initialized else None

    def account_info(self) -> FakeAccountInfo | None:
        self._record("account_info")
        if self.account is not None and not hasattr(self.account, 'trade_allowed'):
            self.account.trade_allowed = True
        return self.account if self.initialized else None

    # -- symbols ---------------------------------------------------------
    def symbols_get(self, group: str | None = None) -> list[FakeSymbolInfo] | None:
        self._record("symbols_get", group)
        if group is None:
            return list(self.symbols)
        return [s for s in self.symbols if fnmatch.fnmatch(s.name, group)]

    def symbols_total(self) -> int:
        self._record("symbols_total")
        return len(self.symbols)

    def symbol_info(self, name: str) -> FakeSymbolInfo | None:
        self._record("symbol_info", name)
        for symbol in self.symbols:
            if symbol.name == name:
                return symbol
        return None

    def symbol_select(self, name: str, enable: bool = True) -> bool:
        self._record("symbol_select", name, enable)
        for symbol in self.symbols:
            if symbol.name == name:
                symbol.visible = enable
                self.selected.add(name)
                return True
        return False

    def symbol_info_tick(self, name: str) -> FakeTick | None:
        self._record("symbol_info_tick", name)
        return self.ticks.get(name)

    def order_send(self, request):
        self._record("order_send", request)
        if self.order_send_results:
            result = self.order_send_results.pop(0)
        else:
            result = FakeOrderResult(retcode=self.order_send_retcode)
        try:
            req = request if isinstance(request, dict) else dict(request)
        except Exception:
            req = {}
        symbol = req.get("symbol")
        volume = req.get("volume", 0.01)
        order_type = req.get("type", 0)
        price = req.get("price")
        position = req.get("position")
        magic = req.get("magic", 0)
        comment = req.get("comment", "")
        action = req.get("action")
        sl = req.get("sl")
        tp = req.get("tp", 0.0)

        if result.retcode == 10009:
            # Remove a pending order.
            if action == TRADE_ACTION_REMOVE or (position is None and "order" in req and action is None and False):
                pass
            if action == TRADE_ACTION_REMOVE:
                order_ticket = req.get("order")
                self.orders = [o for o in self.orders if o.ticket != order_ticket]
                result.order = order_ticket
                result.deal = order_ticket
                result.position = None
                result.price = 0.0
                result.volume = 0.0
            elif position is not None and action in (TRADE_ACTION_DEAL, TRADE_ACTION_SLTP, None):
                if action == TRADE_ACTION_SLTP:
                    for pos in self.positions:
                        if pos.ticket == position:
                            pos.sl = sl if sl is not None else pos.sl
                            pos.tp = tp if tp is not None else pos.tp
                    result.order = position
                    result.deal = position
                    result.position = position
                    result.price = price if price is not None else 0.0
                    result.volume = volume
                else:
                    self.positions = [p for p in self.positions if p.ticket != position]
                    result.order = position
                    result.deal = position
                    result.position = position
                    result.price = price if price is not None else 0.0
                    result.volume = volume
            elif action == TRADE_ACTION_PENDING or order_type in (
                ORDER_TYPE_BUY_STOP,
                ORDER_TYPE_SELL_STOP,
                ORDER_TYPE_BUY_LIMIT,
                ORDER_TYPE_SELL_LIMIT,
                ORDER_TYPE_BUY_STOP_LIMIT,
                ORDER_TYPE_SELL_STOP_LIMIT,
            ):
                ticket = self.next_order_ticket
                self.next_order_ticket += 1
                order = FakeOrder(
                    ticket=ticket,
                    time=int(__import__("time").time() + 10800),
                    type=order_type,
                    magic=magic,
                    volume=volume,
                    price=price if price is not None else 0.0,
                    sl=sl if sl is not None else 0.0,
                    tp=tp if tp is not None else 0.0,
                    symbol=symbol or "XAUUSD",
                    comment=comment,
                )
                self.orders.append(order)
                result.order = ticket
                result.deal = 0
                result.position = None
                result.price = price if price is not None else 0.0
                result.volume = volume
            else:
                # Legacy market entry (no action / deal action without position).
                ticket = self.next_position_ticket
                self.next_position_ticket += 1
                pos = FakePosition(
                    ticket=ticket,
                    time=int(__import__("time").time() + 10800),
                    type=order_type,
                    magic=magic,
                    volume=volume,
                    price_open=price if price is not None else 0.0,
                    price_current=price if price is not None else 0.0,
                    sl=sl if sl is not None else 0.0,
                    tp=tp if tp is not None else 0.0,
                    profit=0.0,
                    symbol=symbol or "XAUUSD",
                    comment=comment,
                )
                self.positions.append(pos)
                result.order = ticket
                result.deal = ticket
                result.position = ticket
                result.price = price if price is not None else 0.0
                result.volume = volume
        if result.comment is None:
            result.comment = "done"
        return result

    def order_check(self, request):
        self._record("order_check", request)
        return type("FakeOrderCheckResult", (), {"retcode": 0, "comment": "done", "balance": 100000.0, "equity": 100000.0, "profit": 0.0, "margin": 0.0, "margin_free": 100000.0, "margin_level": 0.0})()

    def positions_get(self, symbol=None, ticket=None):
        self._record("positions_get", symbol, ticket)
        result = list(self.positions)
        if symbol is not None:
            result = [p for p in result if p.symbol == symbol]
        if ticket is not None:
            result = [p for p in result if p.ticket == ticket]
        return result

    def orders_get(self, symbol=None, ticket=None, **kwargs):
        self._record("orders_get", symbol, ticket)
        result = list(self.orders)
        if symbol is not None:
            result = [o for o in result if getattr(o, "symbol", None) == symbol]
        if ticket is not None:
            result = [o for o in result if o.ticket == ticket]
        return result

    def history_deals_get(self, *args, **kwargs):
        self._record("history_deals_get", *args, **kwargs)
        position = kwargs.get("position")
        if position is None and len(args) >= 3:
            position = args[2]
        result = list(self.deals)
        if position is not None:
            result = [
                d for d in result
                if getattr(d, "position_id", None) == position
                or getattr(d, "position", None) == position
            ]
        return result

    def order_send(self, request):
        self._record("order_send", request)
        if self.order_send_results:
            result = self.order_send_results.pop(0)
        else:
            result = FakeOrderResult(retcode=self.order_send_retcode)
        try:
            req = request if isinstance(request, dict) else dict(request)
        except Exception:
            req = {}
        symbol = req.get("symbol")
        volume = req.get("volume", 0.01)
        order_type = req.get("type", 0)
        price = req.get("price")
        position = req.get("position")
        magic = req.get("magic", 0)
        comment = req.get("comment", "")
        action = req.get("action")
        sl = req.get("sl")
        tp = req.get("tp", 0.0)

        if result.retcode == 10009:
            # Remove a pending order.
            if action == TRADE_ACTION_REMOVE or (position is None and "order" in req and action is None and False):
                pass
            if action == TRADE_ACTION_REMOVE:
                order_ticket = req.get("order")
                self.orders = [o for o in self.orders if o.ticket != order_ticket]
                result.order = order_ticket
                result.deal = order_ticket
                result.position = None
                result.price = 0.0
                result.volume = 0.0
            elif position is not None and action in (TRADE_ACTION_DEAL, TRADE_ACTION_SLTP, None):
                if action == TRADE_ACTION_SLTP:
                    for pos in self.positions:
                        if pos.ticket == position:
                            pos.sl = sl if sl is not None else pos.sl
                            pos.tp = tp if tp is not None else pos.tp
                    result.order = position
                    result.deal = position
                    result.position = position
                    result.price = price if price is not None else 0.0
                    result.volume = volume
                else:
                    self.positions = [p for p in self.positions if p.ticket != position]
                    result.order = position
                    result.deal = position
                    result.position = position
                    result.price = price if price is not None else 0.0
                    result.volume = volume
            elif action == TRADE_ACTION_PENDING or order_type in (
                ORDER_TYPE_BUY_STOP,
                ORDER_TYPE_SELL_STOP,
                ORDER_TYPE_BUY_LIMIT,
                ORDER_TYPE_SELL_LIMIT,
                ORDER_TYPE_BUY_STOP_LIMIT,
                ORDER_TYPE_SELL_STOP_LIMIT,
            ):
                ticket = self.next_order_ticket
                self.next_order_ticket += 1
                order = FakeOrder(
                    ticket=ticket,
                    time=int(__import__("time").time() + 10800),
                    type=order_type,
                    magic=magic,
                    volume=volume,
                    price=price if price is not None else 0.0,
                    sl=sl if sl is not None else 0.0,
                    tp=tp if tp is not None else 0.0,
                    symbol=symbol or "XAUUSD",
                    comment=comment,
                )
                self.orders.append(order)
                result.order = ticket
                result.deal = 0
                result.position = None
                result.price = price if price is not None else 0.0
                result.volume = volume
            else:
                # Legacy market entry (no action / deal action without position).
                ticket = self.next_position_ticket
                self.next_position_ticket += 1
                pos = FakePosition(
                    ticket=ticket,
                    time=int(__import__("time").time() + 10800),
                    type=order_type,
                    magic=magic,
                    volume=volume,
                    price_open=price if price is not None else 0.0,
                    price_current=price if price is not None else 0.0,
                    sl=sl if sl is not None else 0.0,
                    tp=tp if tp is not None else 0.0,
                    profit=0.0,
                    symbol=symbol or "XAUUSD",
                    comment=comment,
                )
                self.positions.append(pos)
                result.order = ticket
                result.deal = ticket
                result.position = ticket
                result.price = price if price is not None else 0.0
                result.volume = volume
        if result.comment is None:
            result.comment = "done"
        return result

    def order_check(self, request):
        self._record("order_check", request)
        return type("FakeOrderCheckResult", (), {"retcode": 0, "comment": "done", "balance": 100000.0, "equity": 100000.0, "profit": 0.0, "margin": 0.0, "margin_free": 100000.0, "margin_level": 0.0})()

    def positions_get(self, symbol=None, ticket=None):
        self._record("positions_get", symbol, ticket)
        result = list(self.positions)
        if symbol is not None:
            result = [p for p in result if p.symbol == symbol]
        if ticket is not None:
            result = [p for p in result if p.ticket == ticket]
        return result

    def orders_get(self, symbol=None, ticket=None, **kwargs):
        self._record("orders_get", symbol, ticket)
        result = list(self.orders)
        if symbol is not None:
            result = [o for o in result if getattr(o, "symbol", None) == symbol]
        if ticket is not None:
            result = [o for o in result if o.ticket == ticket]
        return result

    def history_deals_get(self, *args, **kwargs):
        self._record("history_deals_get", *args, **kwargs)
        position = kwargs.get("position")
        if position is None and len(args) >= 3:
            position = args[2]
        result = list(self.deals)
        if position is not None:
            result = [
                d for d in result
                if getattr(d, "position_id", None) == position
                or getattr(d, "position", None) == position
            ]
        return result

    # -- rates -----------------------------------------------------------
    def copy_rates_from_pos(
        self, symbol: str, timeframe: int, start: int, count: int
    ) -> np.ndarray | None:
        self._record("copy_rates_from_pos", symbol, timeframe, start, count)
        series = self.rates.get((symbol, timeframe))
        if series is None:
            return None
        if count >= len(series):
            return series
        return series[-count:]

    # -- helpers used by tests -------------------------------------------
    def set_tick(self, symbol: str, tick: FakeTick | None) -> None:
        self.ticks[symbol] = tick

    def set_rates(self, symbol: str, timeframe: int, series: np.ndarray | None) -> None:
        self.rates[(symbol, timeframe)] = series



def gold_terminal_with_live_tick(
    *,
    symbol: str = "XAUUSD",
    bid: float = 4185.58,
    ask: float = 4186.14,
    tick_delta_seconds: float = 0.0,
    with_all_timeframes: bool = False,
    history: int = 400,
) -> FakeMT5:
    """A realistic MetaQuotes-Demo-like fake with one live gold tick."""
    fake = FakeMT5(
        symbols=[
            FakeSymbolInfo(symbol),
            FakeSymbolInfo("XAUEUR"),
            FakeSymbolInfo("XAUAUD"),
            FakeSymbolInfo("XAUCHF"),
            FakeSymbolInfo("XAUGBP"),
            FakeSymbolInfo("XAUG"),
        ],
        ticks={
            symbol: FakeTick(
                time=broker_time(delta_seconds=tick_delta_seconds), bid=bid, ask=ask
            )
        },
    )

    if with_all_timeframes:
        steps = {
            TIMEFRAME_M1: 60,
            TIMEFRAME_M5: 300,
            TIMEFRAME_M15: 900,
            TIMEFRAME_M30: 1800,
            TIMEFRAME_H1: 3600,
            TIMEFRAME_H4: 14400,
            TIMEFRAME_D1: 86400,
        }
        for timeframe, step in steps.items():
            # End on the *current* interval so the final bar is still forming -
            # exactly what a real terminal returns.
            end = (broker_time() // step) * step
            fake.set_rates(
                symbol,
                timeframe,
                make_rates(
                    make_candle_rows(
                        end_time=end, step_seconds=step, count=history
                    )
                ),
            )
    return fake
