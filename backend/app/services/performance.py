"""Read-only MT5 trading-performance reporting.

Authoritative source
--------------------
Every figure here is computed from the MT5 terminal's own deal history via
``history_deals_get`` (https://www.mql5.com/en/docs/python_metatrader5/mt5historydealsget_py).
The dashboard's locally stored cycle history is never treated as a financial
record. The service works whether or not the auto-trading worker is running,
submits nothing, and never touches the reconciliation or execution state.

Deal semantics used (https://www.mql5.com/en/docs/constants/tradingconstants/dealproperties)
--------------------------------------------------------------------------------------------
* ``type``: 0 BUY and 1 SELL are trading deals. 2 BALANCE, 3 CREDIT, 4 CHARGE,
  5 CORRECTION, 6 BONUS, 10 INTEREST, 13/14 DIVIDEND, 15 TAX are non-trading
  account movements. 7/8/9 COMMISSION* are standalone agent-fee deals with no
  position linkage.
* ``entry``: 0 IN (open fill), 1 OUT (close), 2 INOUT (reversal, closes the
  referenced position and opens the opposite one), 3 OUT_BY (close-by).
* ``profit`` is carried by exit-side deals; ``commission``, ``swap`` and
  ``fee`` are signed fields on every deal (costs are normally <= 0).

Accounting rules (the contract every response follows)
-----------------------------------------------------
1. **Trading vs non-trading.** Only type 0/1 deals enter trading P&L. Every
   other deal is a cash movement reported separately - deposits, withdrawals,
   credits and corrections never mix into trading profit.
2. **One position identifier = one trade.** Deals are grouped by
   ``position_id``. A trade is *completed* when its group contains at least
   one exit-side deal (OUT / INOUT / OUT_BY). Multiple entry fills and partial
   closes of one position stay one trade - never several.
3. **Net trade P&L** = Σ profit + Σ commission + Σ swap + Σ fee over all deals
   of the position. Gross = Σ profit. Costs = Σ (commission + swap + fee),
   signed as booked (negative reduces the result). Net = gross + costs.
   Standalone agent-fee deals (types 7-9) are added to the period's costs but
   never attributed to a specific trade.
4. **Attribution.** A trade is reported on the day of its *last* exit deal,
   converted from broker-server time to the reporting timezone. A trade whose
   entry lies before the selected window still appears (on its close day) with
   its full net result; its entry fields then render as unavailable.
5. **Wins / losses / win rate.** Net > 0 is a win, net < 0 is a loss, net == 0
   is breakeven: counted as a closed trade and in the denominator, as neither
   win nor loss. ``win_rate = wins / closed_trades`` (``None`` without trades).
6. **Floating P&L** comes from currently open positions (profit + swap) and is
   always reported separately; entry commission is unknown until close, so
   floating excludes it.
7. **Time.** Deal ``time`` is a broker-server-local epoch. True UTC instant =
   epoch − measured broker offset. All day/week/month boundaries are computed
   in the configured reporting timezone via ``zoneinfo`` (DST-safe).
8. **Failure semantics.** A failed history query (``None`` or exception) is
   *not* an empty result: responses carry ``data_available: false`` and the
   reason. A successful query with zero deals is available data with zeros and
   ``deals_checked: 0``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone, time as time_cls
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..logging_config import get_logger
from ..schemas.performance import (
    CashMovement,
    DailyPerformanceItem,
    DailyPerformanceResponse,
    Direction,
    FloatingPnl,
    PerformanceCosts,
    PerformanceFilters,
    PerformanceSummary,
    PerformanceTrade,
    PerformanceTradesResponse,
)
from .market_monitor import MarketMonitor

logger = get_logger(__name__)

# MT5 deal type constants (DEAL_TYPE_*).
_DEAL_TYPE_BUY = 0
_DEAL_TYPE_SELL = 1
# Standalone agent-fee deal types: costs without a position linkage.
_FEE_DEAL_TYPES = {7, 8, 9}
# Human names for the non-trading movement kinds reported separately.
_MOVEMENT_NAMES: dict[int, str] = {
    2: "balance",
    3: "credit",
    4: "charge",
    5: "correction",
    6: "bonus",
    10: "interest",
    11: "buy_canceled",
    12: "sell_canceled",
    13: "dividend",
    14: "dividend_franked",
    15: "tax",
}

_DEAL_ENTRY_IN = 0
_DEAL_ENTRY_OUT = 1
_DEAL_ENTRY_INOUT = 2
_DEAL_ENTRY_OUT_BY = 3
_EXIT_ENTRIES = {_DEAL_ENTRY_OUT, _DEAL_ENTRY_INOUT, _DEAL_ENTRY_OUT_BY}

# Generous margin around the requested window so broker-clock skew and the
# entry-side deals of trades that close inside the window are always fetched.
_WINDOW_MARGIN_DAYS = 3

_ACCOUNTING_RULE = (
    "Net P&L per trade = sum(profit) + sum(commission) + sum(swap) + sum(fee) "
    "over all deals of one position identifier (multiple fills and partial "
    "closes stay one trade). Gross = sum(profit); costs are signed as booked "
    "by MT5. A trade is reported on the day of its last exit deal "
    "(reporting timezone). Standalone broker fee deals count as period costs "
    "without position attribution. Deposits, withdrawals, credits, "
    "corrections and similar movements are excluded from trading P&L and "
    "listed separately. Floating P&L from open positions (profit + swap) is "
    "reported separately and never merged into realized results."
)


@dataclass
class _TradeBuilder:
    """Mutable accumulator for one position identifier's deal lifecycle."""

    position_id: int
    deals: list[Any] = field(default_factory=list)

    @property
    def entry_deals(self) -> list[Any]:
        return [deal for deal in self.deals if _get(deal, "entry") == _DEAL_ENTRY_IN]

    @property
    def exit_deals(self) -> list[Any]:
        return [deal for deal in self.deals if _get(deal, "entry") in _EXIT_ENTRIES]


def _get(obj: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(obj, name)
    except Exception:  # noqa: BLE001 - third-party result objects
        return default


def _as_float(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if result == result else 0.0  # NaN guard


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _round2(value: float) -> float:
    return round(value + 0.0, 2)


class PerformanceService:
    """Computes account performance summaries from MT5 deal history."""

    def __init__(self, connection: Any, monitor: MarketMonitor, settings: Any) -> None:
        self._connection = connection
        self._monitor = monitor
        self._settings = settings
        try:
            self._tz = ZoneInfo(settings.report_timezone)
            self._timezone_label = settings.report_timezone
        except (ZoneInfoNotFoundError, ValueError, AttributeError):
            logger.warning(
                "REPORT_TIMEZONE %r is not a valid IANA timezone; performance "
                "reporting falls back to UTC.",
                getattr(settings, "report_timezone", None),
            )
            self._tz = ZoneInfo("UTC")
            self._timezone_label = "UTC"
        self._cache: dict[tuple[Any, ...], tuple[float, Any]] = {}
        self._cache_seconds = int(getattr(settings, "performance_cache_seconds", 10))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def summary(
        self,
        *,
        preset: str | None = None,
        start: date_cls | None = None,
        end: date_cls | None = None,
        symbol: str | None = None,
        direction: str | None = None,
        magic: int | None = None,
    ) -> PerformanceSummary:
        return await self._compute(
            PerformanceSummary,
            preset=preset,
            start=start,
            end=end,
            symbol=symbol,
            direction=direction,
            magic=magic,
        )

    async def daily(
        self,
        *,
        preset: str | None = None,
        start: date_cls | None = None,
        end: date_cls | None = None,
        symbol: str | None = None,
        direction: str | None = None,
        magic: int | None = None,
    ) -> DailyPerformanceResponse:
        return await self._compute(
            DailyPerformanceResponse,
            preset=preset,
            start=start,
            end=end,
            symbol=symbol,
            direction=direction,
            magic=magic,
        )

    async def trades(
        self,
        *,
        preset: str | None = None,
        start: date_cls | None = None,
        end: date_cls | None = None,
        symbol: str | None = None,
        direction: str | None = None,
        magic: int | None = None,
    ) -> PerformanceTradesResponse:
        return await self._compute(
            PerformanceTradesResponse,
            preset=preset,
            start=start,
            end=end,
            symbol=symbol,
            direction=direction,
            magic=magic,
        )

    # ------------------------------------------------------------------
    # Computation
    # ------------------------------------------------------------------
    async def _compute(self, kind: type, **filters: Any) -> Any:
        cache_key = (kind.__name__,) + tuple(
            filters.get(name) for name in ("preset", "start", "end", "symbol", "direction", "magic")
        )
        now = time.monotonic()
        cached = self._cache.get(cache_key)
        if cached and (now - cached[0]) < self._cache_seconds:
            return cached[1]

        result = await self._compute_uncached(kind, **filters)
        if self._cache_seconds > 0:
            self._cache[cache_key] = (now, result)
        return result

    async def _compute_uncached(self, kind: type, **filters: Any) -> Any:
        settings = self._settings
        range_start, range_end, preset_used, range_error = self._resolve_range(
            filters.get("preset"), filters.get("start"), filters.get("end")
        )
        applied = PerformanceFilters(
            preset=preset_used,
            start=range_start,
            end=range_end,
            symbol=filters.get("symbol"),
            direction=filters.get("direction"),  # type: ignore[arg-type]
            magic=filters.get("magic"),
        )
        generated_at = datetime.now(timezone.utc)
        offset = self._broker_offset_seconds()

        if range_error:
            return self._unavailable_response(
                kind, range_start, range_end, applied, generated_at, range_error
            )

        window_start = range_start - timedelta(days=_WINDOW_MARGIN_DAYS)
        window_end_exclusive = range_end + timedelta(days=_WINDOW_MARGIN_DAYS + 1)
        window_error: str | None = None

        account = await self._account()
        deals, error = await self._fetch_deals(window_start, window_end_exclusive, offset)
        positions = await self._fetch_positions()

        if deals is None:
            window_error = error or "MT5 deal history is unavailable"
        if positions is None:
            # Positions feed floating P&L only; the realized summary survives.
            positions = []

        deals = deals or []
        trades, fee_costs, movements, deals_checked = self._build_from_deals(
            deals, range_start, range_end, offset, applied
        )
        floating = self._floating(positions, applied)

        common = {
            "data_available": window_error is None,
            "error": window_error,
            "range_start": range_start,
            "range_end": range_end,
            "reporting_timezone": self._timezone_label,
            "broker_time_offset_seconds": offset,
            "account_currency": _get(account, "currency") if account else None,
            "filters": applied,
            "generated_at": generated_at,
        }

        if kind is PerformanceSummary:
            period_costs = self._period_costs(trades, fee_costs)
            wins = sum(1 for trade in trades if trade.net_pnl > 0)
            return PerformanceSummary(
                **common,
                balance=_round2(_get(account, "balance")) if account else None,
                equity=_round2(_get(account, "equity")) if account else None,
                closed_trades=len(trades),
                wins=wins,
                losses=sum(1 for trade in trades if trade.net_pnl < 0),
                win_rate=round(wins / len(trades), 4) if trades else None,
                gross_pnl=_round2(sum(trade.gross_pnl for trade in trades)),
                costs=period_costs,
                # Each trade's net already carries its own costs; the only
                # addition is standalone fee deals booked without a position.
                net_pnl=_round2(
                    sum(trade.net_pnl for trade in trades) + fee_costs.total
                ),
                floating=floating,
                cash_movements=movements,
                cash_movements_total=_round2(
                    sum(movement.amount for movement in movements)
                ),
                deals_checked=deals_checked,
                positions_matched=len(trades),
                accounting_rule=_ACCOUNTING_RULE,
            )

        if kind is PerformanceTradesResponse:
            return PerformanceTradesResponse(
                **common,
                trades=trades,
                count=len(trades),
            )

        days = self._daily_rows(trades, fee_costs, range_start, range_end)
        totals = self._totals_row(days)
        return DailyPerformanceResponse(
            **common,
            days=days,
            totals=totals,
        )

    # ------------------------------------------------------------------
    # Range resolution
    # ------------------------------------------------------------------
    def _resolve_range(
        self,
        preset: str | None,
        start: date_cls | None,
        end: date_cls | None,
    ) -> tuple[date_cls, date_cls, str | None, str | None]:
        """Resolve the reporting range in the reporting timezone.

        Returns ``(start, end, preset_used, error)``. ``end`` is inclusive.
        """
        today = datetime.now(self._tz).date()
        max_days = int(getattr(self._settings, "performance_max_history_days", 92))

        if start is not None or end is not None:
            if start is None or end is None:
                return today, today, None, (
                    "Custom ranges need both a start and an end date."
                )
            if start > end:
                return today, today, None, "The range start must not be after the end date."
            if (end - start).days + 1 > max_days:
                return today, today, None, (
                    f"The requested range spans more than {max_days} days "
                    "(PERFORMANCE_MAX_HISTORY_DAYS)."
                )
            return start, end, None, None

        name = (preset or "d10").lower()
        if name in ("today", "1d"):
            return today, today, name, None
        if name == "yesterday":
            day = today - timedelta(days=1)
            return day, day, name, None
        if name in ("d10", "last10days", "10d"):
            return today - timedelta(days=9), today, "d10", None
        if name in ("d7", "last7days", "7d"):
            return today - timedelta(days=6), today, "d7", None
        if name in ("d30", "last30days", "30d"):
            return today - timedelta(days=29), today, "d30", None
        if name in ("week", "thisweek"):
            # Monday-start weeks, computed in the reporting timezone.
            weekday = today.weekday()  # Monday == 0
            return today - timedelta(days=weekday), today, "week", None
        if name in ("month", "thismonth"):
            return today.replace(day=1), today, "month", None
        return today, today, name, f"Unknown range preset {preset!r}."

    # ------------------------------------------------------------------
    # Deal ingestion
    # ------------------------------------------------------------------
    def _build_from_deals(
        self,
        deals: list[Any],
        range_start: date_cls,
        range_end: date_cls,
        offset: int | None,
        applied: PerformanceFilters,
    ) -> tuple[list[PerformanceTrade], PerformanceCosts, list[CashMovement], int]:
        """Group deals into trades, costs and cash movements.

        Returns ``(closed_trades_in_range, standalone_fee_costs, movements,
        deals_checked)``. ``deals_checked`` counts every deal the terminal
        returned so an empty-but-successful query is visible in responses.
        """
        builders: dict[int, _TradeBuilder] = {}
        movements: list[CashMovement] = []
        fee_costs = PerformanceCosts()
        # A deal ticket identifies one immutable record. If a terminal ever
        # returns the same ticket twice (pagination overlap, retries), the
        # duplicate is skipped so no profit or cost is ever counted twice.
        seen_tickets: set[int] = set()

        for deal in deals:
            ticket = _as_int(_get(deal, "ticket"))
            if ticket is not None:
                if ticket in seen_tickets:
                    continue
                seen_tickets.add(ticket)
            deal_type = _as_int(_get(deal, "type"))
            if deal_type is None:
                continue
            if deal_type in _FEE_DEAL_TYPES:
                # Standalone broker fee deal: a trading cost, not a trade.
                fee_costs.commission += _as_float(_get(deal, "profit"))
                fee_costs.total += _as_float(_get(deal, "profit"))
                continue
            if deal_type not in (_DEAL_TYPE_BUY, _DEAL_TYPE_SELL):
                movements.append(
                    CashMovement(
                        ticket=_as_int(_get(deal, "ticket")) or 0,
                        type_code=deal_type,
                        type_name=_MOVEMENT_NAMES.get(deal_type, f"type_{deal_type}"),
                        time=self._to_reporting(_get(deal, "time"), offset),
                        amount=_round2(_as_float(_get(deal, "profit"))),
                        comment=_get(deal, "comment"),
                    )
                )
                continue

            position_id = _as_int(_get(deal, "position_id")) or _as_int(
                _get(deal, "position")
            )
            if position_id is None:
                # A trading deal without a position reference cannot be
                # attributed; treat it as a movement so nothing disappears.
                movements.append(
                    CashMovement(
                        ticket=_as_int(_get(deal, "ticket")) or 0,
                        type_code=deal_type,
                        type_name="unattributed_trade_deal",
                        time=self._to_reporting(_get(deal, "time"), offset),
                        amount=_round2(_as_float(_get(deal, "profit"))),
                        comment=_get(deal, "comment"),
                    )
                )
                continue
            builders.setdefault(position_id, _TradeBuilder(position_id)).deals.append(deal)

        trades: list[PerformanceTrade] = []
        for builder in builders.values():
            if not builder.exit_deals:
                # Opened (or still open) without a confirmed close in history:
                # never counted as a completed trade.
                continue
            trade = self._build_trade(builder, offset)
            if not self._trade_in_filters(trade, applied, range_start, range_end):
                continue
            trades.append(trade)

        trades.sort(
            key=lambda trade: (
                trade.close_day or range_start,
                trade.position_id,
            )
        )
        return trades, fee_costs, movements, len(deals)

    def _build_trade(self, builder: _TradeBuilder, offset: int | None) -> PerformanceTrade:
        deals = sorted(builder.deals, key=lambda deal: _as_int(_get(deal, "time")) or 0)
        entries = builder.entry_deals
        exits = builder.exit_deals

        gross = sum(_as_float(_get(deal, "profit")) for deal in deals)
        commission = sum(_as_float(_get(deal, "commission")) for deal in deals)
        swap = sum(_as_float(_get(deal, "swap")) for deal in deals)
        fee = sum(_as_float(_get(deal, "fee")) for deal in deals)
        costs = PerformanceCosts(
            commission=_round2(commission),
            swap=_round2(swap),
            fee=_round2(fee),
            total=_round2(commission + swap + fee),
        )

        entry_volume = sum(_as_float(_get(deal, "volume")) for deal in entries)
        exit_volume = sum(_as_float(_get(deal, "volume")) for deal in exits)
        entry_price = self._volume_weighted_price(entries)
        exit_price = self._volume_weighted_price(exits)

        first_entry = min(entries, key=lambda deal: _as_int(_get(deal, "time")) or 0) if entries else None
        last_exit = max(exits, key=lambda deal: _as_int(_get(deal, "time")) or 0)

        direction: Direction | None = None
        if entries:
            deal_type = _as_int(_get(first_entry, "type"))
            direction = "buy" if deal_type == _DEAL_TYPE_BUY else "sell" if deal_type == _DEAL_TYPE_SELL else None

        exit_time = self._to_reporting(_get(last_exit, "time"), offset)
        return PerformanceTrade(
            position_id=builder.position_id,
            symbol=_get(deals[0], "symbol"),
            direction=direction,
            magic=_as_int(_get(first_entry, "magic")) if first_entry else _as_int(_get(deals[0], "magic")),
            comment=_get(deals[0], "comment"),
            opened_volume=_round2(entry_volume),
            closed_volume=_round2(exit_volume),
            entry_time=self._to_reporting(_get(first_entry, "time"), offset) if first_entry else None,
            exit_time=exit_time,
            entry_price=entry_price,
            exit_price=exit_price,
            gross_pnl=_round2(gross),
            costs=costs,
            net_pnl=_round2(gross + commission + swap + fee),
            deal_tickets=[
                ticket
                for ticket in (_as_int(_get(deal, "ticket")) for deal in deals)
                if ticket is not None
            ],
            order_tickets=sorted(
                {
                    ticket
                    for ticket in (_as_int(_get(deal, "order")) for deal in deals)
                    if ticket is not None
                }
            ),
            close_day=exit_time.date() if exit_time else None,
        )

    def _trade_in_filters(
        self,
        trade: PerformanceTrade,
        applied: PerformanceFilters,
        range_start: date_cls,
        range_end: date_cls,
    ) -> bool:
        if applied.symbol and (trade.symbol or "").upper() != applied.symbol.upper():
            return False
        if applied.direction and trade.direction != applied.direction:
            return False
        if applied.magic is not None and trade.magic != applied.magic:
            return False
        if trade.close_day is None or not (range_start <= trade.close_day <= range_end):
            return False
        return True

    @staticmethod
    def _volume_weighted_price(deals: list[Any]) -> float | None:
        total_volume = sum(_as_float(_get(deal, "volume")) for deal in deals)
        if total_volume <= 0:
            return None
        weighted = sum(
            _as_float(_get(deal, "price")) * _as_float(_get(deal, "volume")) for deal in deals
        )
        return round(weighted / total_volume, 5)

    # ------------------------------------------------------------------
    # Daily rows
    # ------------------------------------------------------------------
    def _daily_rows(
        self,
        trades: list[PerformanceTrade],
        fee_costs: PerformanceCosts,
        range_start: date_cls,
        range_end: date_cls,
    ) -> list[DailyPerformanceItem]:
        days: list[DailyPerformanceItem] = []
        day = range_start
        while day <= range_end:
            day_trades = [trade for trade in trades if trade.close_day == day]
            commission = sum(trade.costs.commission for trade in day_trades)
            swap = sum(trade.costs.swap for trade in day_trades)
            fee = sum(trade.costs.fee for trade in day_trades)
            gross = sum(trade.gross_pnl for trade in day_trades)
            wins = sum(1 for trade in day_trades if trade.net_pnl > 0)
            losses = sum(1 for trade in day_trades if trade.net_pnl < 0)
            days.append(
                DailyPerformanceItem(
                    date=day,
                    closed_trades=len(day_trades),
                    wins=wins,
                    losses=losses,
                    gross_pnl=_round2(gross),
                    costs=PerformanceCosts(
                        commission=_round2(commission),
                        swap=_round2(swap),
                        fee=_round2(fee),
                        total=_round2(commission + swap + fee),
                    ),
                    net_pnl=_round2(gross + commission + swap + fee),
                    win_rate=round(wins / len(day_trades), 4) if day_trades else None,
                )
            )
            day += timedelta(days=1)
        return days

    def _totals_row(self, days: list[DailyPerformanceItem]) -> DailyPerformanceItem:
        if not days:
            return DailyPerformanceItem(date=datetime.now(self._tz).date())
        closed = sum(day.closed_trades for day in days)
        wins = sum(day.wins for day in days)
        losses = sum(day.losses for day in days)
        return DailyPerformanceItem(
            date=days[-1].date,
            closed_trades=closed,
            wins=wins,
            losses=losses,
            gross_pnl=_round2(sum(day.gross_pnl for day in days)),
            costs=PerformanceCosts(
                commission=_round2(sum(day.costs.commission for day in days)),
                swap=_round2(sum(day.costs.swap for day in days)),
                fee=_round2(sum(day.costs.fee for day in days)),
                total=_round2(sum(day.costs.total for day in days)),
            ),
            net_pnl=_round2(sum(day.net_pnl for day in days)),
            win_rate=round(wins / closed, 4) if closed else None,
        )

    @staticmethod
    def _period_costs(
        trades: list[PerformanceTrade], fee_costs: PerformanceCosts
    ) -> PerformanceCosts:
        commission = sum(trade.costs.commission for trade in trades) + fee_costs.commission
        swap = sum(trade.costs.swap for trade in trades)
        fee = sum(trade.costs.fee for trade in trades)
        return PerformanceCosts(
            commission=_round2(commission),
            swap=_round2(swap),
            fee=_round2(fee),
            total=_round2(commission + swap + fee),
        )

    # ------------------------------------------------------------------
    # Terminal reads (all read-only, all serialised via the connection)
    # ------------------------------------------------------------------
    async def _fetch_deals(
        self,
        window_start: date_cls,
        window_end_exclusive: date_cls,
        offset: int | None,
    ) -> tuple[list[Any] | None, str | None]:
        """Query ``history_deals_get`` over the bounded window.

        Returns ``(deals, None)`` on success and ``(None, reason)`` when the
        API failed - a failed query is never presented as "no deals".
        """
        getter = getattr(self._connection.mt5, "history_deals_get", None)
        if getter is None:
            return None, "history_deals_get is unavailable on this terminal connection"
        offset_seconds = offset or 0
        # MT5 expects naive datetimes interpreted on the server clock: a true
        # UTC instant T corresponds to server wall clock T + offset.
        from_server = (
            datetime.combine(window_start, time_cls.min, tzinfo=timezone.utc)
            + timedelta(seconds=offset_seconds)
        ).replace(tzinfo=None)
        to_server = (
            datetime.combine(window_end_exclusive, time_cls.min, tzinfo=timezone.utc)
            + timedelta(seconds=offset_seconds)
        ).replace(tzinfo=None)
        try:
            deals = await self._connection.acall(getter, from_server, to_server)
        except Exception as exc:  # noqa: BLE001 - history failure is reportable
            return None, f"history_deals_get raised: {exc}"
        if deals is None:
            return None, "history_deals_get returned None (API error)"
        return list(deals), None

    async def _fetch_positions(self) -> list[Any] | None:
        getter = getattr(self._connection.mt5, "positions_get", None)
        if getter is None:
            return None
        try:
            positions = await self._connection.acall(getter)
        except Exception:  # noqa: BLE001
            return None
        return list(positions) if positions is not None else None

    async def _account(self) -> Any | None:
        getter = getattr(self._connection.mt5, "account_info", None)
        if getter is None:
            return None
        try:
            return await self._connection.acall(getter)
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # Time and floating P&L
    # ------------------------------------------------------------------
    def _broker_offset_seconds(self) -> int | None:
        """The measured broker-clock offset, when the monitor has one."""
        getter = getattr(self._monitor, "broker_clock_offset_seconds", None)
        if getter is None:
            return None
        try:
            value = getter()
        except Exception:  # noqa: BLE001
            return None
        return int(value) if value is not None else None

    def _to_reporting(self, epoch_seconds: Any, offset: int | None) -> datetime | None:
        """Broker-local epoch -> aware datetime in the reporting timezone.

        ``None`` when the deal carries no usable time: never fabricated.
        """
        seconds = _as_int(epoch_seconds)
        if seconds is None:
            return None
        utc = datetime.fromtimestamp(seconds - (offset or 0), tz=timezone.utc)
        return utc.astimezone(self._tz)

    def _floating(
        self, positions: list[Any] | None, applied: PerformanceFilters
    ) -> FloatingPnl:
        result = FloatingPnl()
        for position in positions or []:
            if applied.symbol and (
                (_get(position, "symbol") or "").upper() != applied.symbol.upper()
            ):
                continue
            if applied.magic is not None and _as_int(_get(position, "magic")) != applied.magic:
                continue
            profit = _as_float(_get(position, "profit"))
            swap = _as_float(_get(position, "swap"))
            result.open_positions += 1
            result.profit += profit
            result.swap += swap
        result.profit = _round2(result.profit)
        result.swap = _round2(result.swap)
        result.total = _round2(result.profit + result.swap)
        return result

    # ------------------------------------------------------------------
    # Unavailable responses
    # ------------------------------------------------------------------
    def _unavailable_response(
        self,
        kind: type,
        range_start: date_cls,
        range_end: date_cls,
        applied: PerformanceFilters,
        generated_at: datetime,
        error: str,
    ) -> Any:
        common = {
            "data_available": False,
            "error": error,
            "range_start": range_start,
            "range_end": range_end,
            "reporting_timezone": self._timezone_label,
            "filters": applied,
            "generated_at": generated_at,
        }
        if kind is PerformanceSummary:
            return PerformanceSummary(
                **common,
                accounting_rule=_ACCOUNTING_RULE,
            )
        if kind is DailyPerformanceResponse:
            return DailyPerformanceResponse(**common)
        return PerformanceTradesResponse(**common)
