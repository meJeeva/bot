"""Performance reporting: deterministic accounting over fake MT5 history.

Every test drives the real ``PerformanceService`` (or the real FastAPI app)
against ``tests.fakes.FakeMT5``. All amounts come from the fake's deal
records; nothing is fabricated inside the service under test. The fake
server's clock runs at UTC+3 (``DEFAULT_SERVER_OFFSET_SECONDS``) exactly like
the MetaQuotes-Demo terminal the project was developed against, and reporting
runs in Asia/Kolkata, so every timestamp conversion and day boundary in these
tests exercises the real offset arithmetic.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.mt5.connection import MT5Connection
from app.services.performance import PerformanceService
from tests.fakes import (
    DEFAULT_SERVER_OFFSET_SECONDS,
    FakeDeal,
    FakeMT5,
    FakePosition,
)

IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc

SERVER_OFFSET = DEFAULT_SERVER_OFFSET_SECONDS


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def broker_epoch(utc_moment: datetime) -> int:
    """A broker-server epoch for a true UTC instant (server runs at UTC+3)."""
    return int(utc_moment.timestamp()) + SERVER_OFFSET


def ist_moment(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """A true UTC instant for a wall-clock time in Asia/Kolkata."""
    return datetime(year, month, day, hour, minute, tzinfo=IST).astimezone(UTC)


def build_service(fake: FakeMT5, **overrides) -> PerformanceService:
    settings = Settings(
        _env_file=None,
        report_timezone="Asia/Kolkata",
        performance_cache_seconds=0,
        **overrides,
    )
    connection = MT5Connection(settings, mt5_module=fake)
    connection.initialize_sync()
    monitor = SimpleNamespace(broker_clock_offset_seconds=lambda: SERVER_OFFSET)
    return PerformanceService(connection, monitor, settings)


def closed_trade(
    position_id: int,
    *,
    entry_utc: datetime,
    exit_utc: datetime,
    direction: str = "buy",
    volume: float = 0.1,
    entry_price: float = 2400.0,
    exit_price: float = 2399.0,
    profit: float = 0.0,
    entry_commission: float = -0.5,
    exit_commission: float = -0.5,
    swap: float = 0.0,
    fee: float = 0.0,
    magic: int = 9001,
    symbol: str = "XAUUSD",
    entry_ticket: int | None = None,
    exit_ticket: int | None = None,
) -> list[FakeDeal]:
    """One full position lifecycle: an entry fill and a closing deal."""
    entry_type = 0 if direction == "buy" else 1
    base_ticket = position_id * 10
    return [
        FakeDeal(
            ticket=entry_ticket or base_ticket + 1,
            order=base_ticket + 2,
            position_id=position_id,
            time=broker_epoch(entry_utc),
            type=entry_type,
            entry=0,
            magic=magic,
            volume=volume,
            price=entry_price,
            commission=entry_commission,
            symbol=symbol,
            comment="entry",
            reason=0,
        ),
        FakeDeal(
            ticket=exit_ticket or base_ticket + 3,
            order=base_ticket + 4,
            position_id=position_id,
            time=broker_epoch(exit_utc),
            type=1 - entry_type,
            entry=1,
            magic=magic,
            volume=volume,
            price=exit_price,
            profit=profit,
            commission=exit_commission,
            swap=swap,
            fee=fee,
            symbol=symbol,
            comment="sl",
            reason=4,
        ),
    ]


# ----------------------------------------------------------------------
# Wins, losses, costs
# ----------------------------------------------------------------------
class TestWinsLossesAndCosts:
    async def test_one_winner_one_loser_with_full_costs(self):
        fake = FakeMT5()
        # Winner: +10 gross, entry and exit commission -0.5 each -> net +9.
        fake.deals.extend(
            closed_trade(
                101,
                entry_utc=ist_moment(2026, 10, 12, 10, 0),
                exit_utc=ist_moment(2026, 10, 12, 10, 30),
                profit=10.0,
            )
        )
        # Loser: -6 gross, -1 commissions, -0.25 swap, -0.1 fee -> net -7.35.
        fake.deals.extend(
            closed_trade(
                102,
                entry_utc=ist_moment(2026, 10, 13, 11, 0),
                exit_utc=ist_moment(2026, 10, 13, 11, 20),
                profit=-6.0,
                swap=-0.25,
                fee=-0.1,
            )
        )
        service = build_service(fake)

        summary = await service.summary(
            start=date(2026, 10, 12),
            end=date(2026, 10, 13),
        )

        assert summary.data_available is True
        assert summary.closed_trades == 2
        assert summary.wins == 1
        assert summary.losses == 1
        assert summary.win_rate == 0.5
        assert summary.gross_pnl == 4.0
        assert summary.costs.commission == -2.0
        assert summary.costs.swap == -0.25
        assert summary.costs.fee == -0.1
        assert summary.costs.total == -2.35
        assert summary.net_pnl == 1.65
        assert summary.account_currency == fake.account.currency

    async def test_daily_rows_split_the_same_result(self):
        fake = FakeMT5()
        fake.deals.extend(
            closed_trade(
                101,
                entry_utc=ist_moment(2026, 10, 12, 10, 0),
                exit_utc=ist_moment(2026, 10, 12, 10, 30),
                profit=10.0,
            )
        )
        fake.deals.extend(
            closed_trade(
                102,
                entry_utc=ist_moment(2026, 10, 13, 11, 0),
                exit_utc=ist_moment(2026, 10, 13, 11, 20),
                profit=-6.0,
                swap=-0.25,
                fee=-0.1,
            )
        )
        service = build_service(fake)

        daily = await service.daily(
            start=date(2026, 10, 12),
            end=date(2026, 10, 13),
        )

        assert [day.date for day in daily.days] == [
            date(2026, 10, 12),
            date(2026, 10, 13),
        ]
        day1, day2 = daily.days
        assert day1.closed_trades == 1 and day1.net_pnl == 9.0 and day1.wins == 1
        assert day2.closed_trades == 1 and day2.net_pnl == -7.35 and day2.losses == 1
        assert day1.win_rate == 1.0 and day2.win_rate == 0.0

        totals = daily.totals
        assert totals.closed_trades == 2
        assert totals.net_pnl == 1.65
        assert totals.win_rate == 0.5


# ----------------------------------------------------------------------
# One position identifier is one trade
# ----------------------------------------------------------------------
class TestPositionLifecycle:
    async def test_multiple_entry_fills_stay_one_trade(self):
        fake = FakeMT5()
        moment = ist_moment(2026, 10, 12, 10, 0)
        # Two partial entry fills (0.06 + 0.04) closed by one exit deal.
        fake.deals.extend(
            closed_trade(
                201,
                entry_utc=moment,
                exit_utc=ist_moment(2026, 10, 12, 10, 20),
                volume=0.06,
                entry_price=2400.0,
                profit=4.0,
            )
        )
        fake.deals.append(
            FakeDeal(
                ticket=2012,
                order=202,
                position_id=201,
                time=broker_epoch(moment),
                type=0,
                entry=0,
                magic=9001,
                volume=0.04,
                price=2400.5,
                commission=-0.4,
                symbol="XAUUSD",
                comment="entry",
                reason=0,
            )
        )
        # The single exit deal's volume must now cover both fills.
        for deal in fake.deals:
            if deal.entry == 1 and deal.position_id == 201:
                deal.volume = 0.1
        service = build_service(fake)

        result = await service.trades(
            start=date(2026, 10, 12),
            end=date(2026, 10, 12),
        )

        assert result.count == 1
        trade = result.trades[0]
        assert trade.opened_volume == 0.1
        assert trade.closed_volume == 0.1
        assert trade.gross_pnl == 4.0
        assert trade.costs.commission == -1.4  # -1.0 on the fill + -0.4 on the second fill
        # Entry price is the volume-weighted average of both fills.
        assert trade.entry_price == pytest.approx(2400.2, abs=1e-9)

    async def test_multiple_partial_closes_stay_one_trade(self):
        fake = FakeMT5()
        entry_utc = ist_moment(2026, 10, 12, 10, 0)
        fake.deals.append(
            FakeDeal(
                ticket=3011,
                order=301,
                position_id=301,
                time=broker_epoch(entry_utc),
                type=0,
                entry=0,
                magic=9001,
                volume=0.2,
                price=2400.0,
                commission=-1.0,
                symbol="XAUUSD",
                comment="entry",
                reason=0,
            )
        )
        fake.deals.append(
            FakeDeal(
                ticket=3012,
                order=302,
                position_id=301,
                time=broker_epoch(ist_moment(2026, 10, 12, 10, 10)),
                type=1,
                entry=1,
                magic=9001,
                volume=0.1,
                price=2399.0,
                profit=-2.0,
                commission=-0.3,
                symbol="XAUUSD",
                comment="partial",
                reason=0,
            )
        )
        fake.deals.append(
            FakeDeal(
                ticket=3013,
                order=303,
                position_id=301,
                time=broker_epoch(ist_moment(2026, 10, 12, 10, 30)),
                type=1,
                entry=1,
                magic=9001,
                volume=0.1,
                price=2398.0,
                profit=-3.0,
                commission=-0.3,
                symbol="XAUUSD",
                comment="sl",
                reason=4,
            )
        )
        service = build_service(fake)

        result = await service.trades(
            start=date(2026, 10, 12),
            end=date(2026, 10, 12),
        )

        assert result.count == 1
        trade = result.trades[0]
        assert trade.opened_volume == 0.2
        assert trade.closed_volume == 0.2
        assert trade.gross_pnl == -5.0
        assert trade.costs.commission == -1.6
        assert trade.net_pnl == -6.6
        # Exit price is volume-weighted across both partial closes.
        assert trade.exit_price == pytest.approx(2398.5, abs=1e-9)
        assert set(trade.deal_tickets) == {3011, 3012, 3013}

    async def test_entry_without_exit_history_is_not_a_completed_trade(self):
        fake = FakeMT5()
        fake.deals.append(
            FakeDeal(
                ticket=4011,
                order=401,
                position_id=401,
                time=broker_epoch(ist_moment(2026, 10, 12, 10, 0)),
                type=0,
                entry=0,
                magic=9001,
                volume=0.1,
                price=2400.0,
                commission=-0.5,
                symbol="XAUUSD",
                comment="entry",
                reason=0,
            )
        )
        service = build_service(fake)

        summary = await service.summary(
            start=date(2026, 10, 12),
            end=date(2026, 10, 12),
        )

        assert summary.closed_trades == 0
        assert summary.win_rate is None
        assert summary.deals_checked == 1
        assert summary.net_pnl == 0.0


# ----------------------------------------------------------------------
# Day attribution and ranges
# ----------------------------------------------------------------------
class TestDayAttributionAndRanges:
    async def test_a_trade_belongs_to_the_day_of_its_close(self):
        fake = FakeMT5()
        # Opened yesterday evening, closed today shortly after midnight IST.
        fake.deals.extend(
            closed_trade(
                501,
                entry_utc=ist_moment(2026, 10, 12, 22, 0),
                exit_utc=ist_moment(2026, 10, 13, 0, 5),
                profit=5.0,
            )
        )
        service = build_service(fake)

        result = await service.trades(
            start=date(2026, 10, 12),
            end=date(2026, 10, 13),
        )

        assert result.count == 1
        trade = result.trades[0]
        assert trade.close_day == date(2026, 10, 13)
        # The whole lifecycle - including the entry booked the day before -
        # is attributed to the close day.
        assert trade.net_pnl == 4.0
        assert trade.entry_time is not None
        assert trade.exit_time is not None

    async def test_trades_around_midnight_land_on_their_own_days(self):
        fake = FakeMT5()
        fake.deals.extend(
            closed_trade(
                601,
                entry_utc=ist_moment(2026, 10, 12, 23, 40),
                exit_utc=ist_moment(2026, 10, 12, 23, 58),
                profit=2.0,
            )
        )
        fake.deals.extend(
            closed_trade(
                602,
                entry_utc=ist_moment(2026, 10, 13, 0, 2),
                exit_utc=ist_moment(2026, 10, 13, 0, 20),
                profit=-1.0,
            )
        )
        service = build_service(fake)

        daily = await service.daily(
            start=date(2026, 10, 12),
            end=date(2026, 10, 13),
        )

        by_date = {day.date: day for day in daily.days}
        assert by_date[date(2026, 10, 12)].net_pnl == 1.0
        assert by_date[date(2026, 10, 13)].net_pnl == -2.0

    async def test_weekly_monthly_and_custom_ranges(self):
        fake = FakeMT5()
        for index, position in enumerate((701, 702, 703), start=1):
            fake.deals.extend(
                closed_trade(
                    position,
                    entry_utc=ist_moment(2026, 10, 12, 9, index),
                    exit_utc=ist_moment(2026, 10, 12 + index - 1, 10, index),
                    profit=3.0 * index,
                )
            )
        service = build_service(fake)

        # Custom three-day range spanning 2026-10-12 .. 2026-10-14.
        result = await service.trades(
            start=date(2026, 10, 12),
            end=date(2026, 10, 14),
        )
        assert result.count == 3

        daily = await service.daily(
            start=date(2026, 10, 12),
            end=date(2026, 10, 14),
        )
        assert len(daily.days) == 3
        assert daily.totals.net_pnl == 15.0

        # Presets resolve their boundaries in the reporting timezone.
        ten_days = await service.summary(preset="d10")
        assert (ten_days.range_end - ten_days.range_start).days == 9
        assert ten_days.range_end >= ten_days.range_start

        monthly = await service.summary(preset="month")
        assert monthly.range_start.day == 1
        assert monthly.range_end >= monthly.range_start

        weekly = await service.summary(preset="week")
        assert weekly.range_end >= weekly.range_start

    async def test_over_bound_custom_range_is_reported_unavailable(self):
        service = build_service(FakeMT5())
        summary = await service.summary(
            start=date(2026, 1, 1),
            end=date(2026, 12, 31),
        )
        assert summary.data_available is False
        assert "92" in (summary.error or "")


# ----------------------------------------------------------------------
# Filters
# ----------------------------------------------------------------------
class TestFilters:
    async def test_symbol_direction_and_magic_filters(self):
        fake = FakeMT5()
        fake.deals.extend(
            closed_trade(
                801,
                entry_utc=ist_moment(2026, 10, 12, 9, 0),
                exit_utc=ist_moment(2026, 10, 12, 9, 30),
                direction="buy",
                profit=5.0,
            )
        )
        fake.deals.extend(
            closed_trade(
                802,
                entry_utc=ist_moment(2026, 10, 12, 10, 0),
                exit_utc=ist_moment(2026, 10, 12, 10, 30),
                direction="sell",
                symbol="XAUUSDm",
                profit=-2.0,
            )
        )
        fake.deals.extend(
            closed_trade(
                803,
                entry_utc=ist_moment(2026, 10, 12, 11, 0),
                exit_utc=ist_moment(2026, 10, 12, 11, 30),
                direction="buy",
                magic=777,
                profit=1.0,
            )
        )
        service = build_service(fake)

        by_symbol = await service.summary(
            start=date(2026, 10, 12),
            end=date(2026, 10, 12),
            symbol="xauusd",  # case-insensitive
        )
        # Both XAUUSD trades match (801 and 803); the XAUUSDm variant does not.
        assert by_symbol.closed_trades == 2
        assert by_symbol.net_pnl == 4.0

        sells = await service.summary(
            start=date(2026, 10, 12),
            end=date(2026, 10, 12),
            direction="sell",
        )
        assert sells.closed_trades == 1
        assert sells.net_pnl == -3.0

        by_magic = await service.summary(
            start=date(2026, 10, 12),
            end=date(2026, 10, 12),
            magic=777,
        )
        assert by_magic.closed_trades == 1
        assert by_magic.net_pnl == 0.0

        unfiltered = await service.summary(
            start=date(2026, 10, 12),
            end=date(2026, 10, 12),
        )
        assert unfiltered.closed_trades == 3


# ----------------------------------------------------------------------
# Floating P&L stays separate
# ----------------------------------------------------------------------
class TestFloatingSeparate:
    async def test_open_positions_are_reported_outside_realized_results(self):
        fake = FakeMT5()
        fake.deals.extend(
            closed_trade(
                901,
                entry_utc=ist_moment(2026, 10, 12, 9, 0),
                exit_utc=ist_moment(2026, 10, 12, 9, 30),
                profit=5.0,
            )
        )
        fake.positions.append(
            FakePosition(
                ticket=950,
                identifier=950,
                magic=9001,
                volume=0.1,
                profit=12.5,
                swap=-0.3,
                symbol="XAUUSD",
            )
        )
        service = build_service(fake)

        summary = await service.summary(
            start=date(2026, 10, 12),
            end=date(2026, 10, 12),
        )

        assert summary.floating.open_positions == 1
        assert summary.floating.profit == 12.5
        assert summary.floating.swap == -0.3
        assert summary.floating.total == 12.2
        # Realized results are untouched by the open position.
        assert summary.net_pnl == 4.0
        assert summary.closed_trades == 1

    async def test_symbol_filter_also_scopes_floating(self):
        fake = FakeMT5()
        fake.positions.append(
            FakePosition(ticket=951, identifier=951, magic=9001, profit=10.0, symbol="XAUUSD")
        )
        fake.positions.append(
            FakePosition(ticket=952, identifier=952, magic=9001, profit=99.0, symbol="XAUEUR")
        )
        service = build_service(fake)

        summary = await service.summary(
            start=date(2026, 10, 12),
            end=date(2026, 10, 12),
            symbol="XAUUSD",
        )

        assert summary.floating.open_positions == 1
        assert summary.floating.total == 10.0


# ----------------------------------------------------------------------
# Cash movements and standalone fees
# ----------------------------------------------------------------------
class TestCashMovementsAndFees:
    async def test_deposits_and_corrections_never_mix_into_trading_profit(self):
        fake = FakeMT5()
        fake.deals.extend(
            closed_trade(
                1001,
                entry_utc=ist_moment(2026, 10, 12, 9, 0),
                exit_utc=ist_moment(2026, 10, 12, 9, 30),
                profit=5.0,
            )
        )
        fake.deals.append(
            FakeDeal(
                ticket=1002,
                time=broker_epoch(ist_moment(2026, 10, 12, 8, 0)),
                type=2,  # DEAL_TYPE_BALANCE: a deposit
                entry=0,
                profit=500.0,
                comment="deposit",
            )
        )
        fake.deals.append(
            FakeDeal(
                ticket=1003,
                time=broker_epoch(ist_moment(2026, 10, 12, 8, 5)),
                type=5,  # DEAL_TYPE_CORRECTION
                entry=0,
                profit=-20.0,
                comment="broker correction",
            )
        )
        service = build_service(fake)

        summary = await service.summary(
            start=date(2026, 10, 12),
            end=date(2026, 10, 12),
        )

        assert summary.net_pnl == 4.0  # trading result only
        assert {movement.type_name for movement in summary.cash_movements} == {
            "balance",
            "correction",
        }
        assert summary.cash_movements_total == 480.0

    async def test_standalone_fee_deals_are_costs_without_a_trade(self):
        fake = FakeMT5()
        fake.deals.extend(
            closed_trade(
                1101,
                entry_utc=ist_moment(2026, 10, 12, 9, 0),
                exit_utc=ist_moment(2026, 10, 12, 9, 30),
                profit=5.0,
            )
        )
        # DEAL_TYPE_COMMISSION_DAILY: agent fee booked without position linkage.
        fake.deals.append(
            FakeDeal(
                ticket=1102,
                time=broker_epoch(ist_moment(2026, 10, 12, 23, 50)),
                type=8,
                entry=0,
                profit=-3.0,
                comment="daily commission",
            )
        )
        service = build_service(fake)

        summary = await service.summary(
            start=date(2026, 10, 12),
            end=date(2026, 10, 12),
        )

        assert summary.closed_trades == 1
        # Gross is trading profit only; the fee deal reaches costs and net.
        assert summary.gross_pnl == 5.0
        assert summary.costs.total == -4.0
        assert summary.net_pnl == 1.0


# ----------------------------------------------------------------------
# Robustness
# ----------------------------------------------------------------------
class TestRobustness:
    async def test_duplicate_deal_tickets_are_counted_once(self):
        fake = FakeMT5()
        trade = closed_trade(
            1201,
            entry_utc=ist_moment(2026, 10, 12, 9, 0),
            exit_utc=ist_moment(2026, 10, 12, 9, 30),
            profit=5.0,
        )
        fake.deals.extend(trade)
        fake.deals.extend(trade)  # the same records returned twice
        service = build_service(fake)

        summary = await service.summary(
            start=date(2026, 10, 12),
            end=date(2026, 10, 12),
        )

        assert summary.closed_trades == 1
        assert summary.net_pnl == 4.0

    async def test_failed_history_query_is_unavailable_not_zero(self):
        fake = FakeMT5()
        service = build_service(fake)
        original = fake.history_deals_get
        fake.history_deals_get = lambda *args, **kwargs: None

        summary = await service.summary(
            start=date(2026, 10, 12),
            end=date(2026, 10, 12),
        )

        assert summary.data_available is False
        assert "None" in (summary.error or "")
        fake.history_deals_get = original

    async def test_raising_history_query_is_reported(self):
        fake = FakeMT5()

        def raising(*args, **kwargs):
            raise RuntimeError("ipc timeout")

        fake.history_deals_get = raising
        service = build_service(fake)

        summary = await service.summary(
            start=date(2026, 10, 12),
            end=date(2026, 10, 12),
        )

        assert summary.data_available is False
        assert "raised" in (summary.error or "")

    async def test_successful_empty_history_is_available_data_with_zeros(self):
        fake = FakeMT5()
        service = build_service(fake)

        summary = await service.summary(
            start=date(2026, 10, 12),
            end=date(2026, 10, 12),
        )

        assert summary.data_available is True
        assert summary.error is None
        assert summary.deals_checked == 0
        assert summary.closed_trades == 0
        assert summary.net_pnl == 0.0
        assert summary.win_rate is None

    async def test_results_survive_a_backend_restart(self):
        fake = FakeMT5()
        fake.deals.extend(
            closed_trade(
                1301,
                entry_utc=ist_moment(2026, 10, 12, 9, 0),
                exit_utc=ist_moment(2026, 10, 12, 9, 30),
                profit=5.0,
            )
        )
        first = build_service(fake)
        second = build_service(fake)  # a fresh process over the same account

        before = await first.summary(
            start=date(2026, 10, 12),
            end=date(2026, 10, 12),
        )
        after = await second.summary(
            start=date(2026, 10, 12),
            end=date(2026, 10, 12),
        )

        assert before.net_pnl == after.net_pnl == 4.0
        assert before.closed_trades == after.closed_trades == 1
        assert before.reporting_timezone == after.reporting_timezone

    async def test_reporting_api_never_submits_orders(self):
        fake = FakeMT5()
        fake.deals.extend(
            closed_trade(
                1401,
                entry_utc=ist_moment(2026, 10, 12, 9, 0),
                exit_utc=ist_moment(2026, 10, 12, 9, 30),
                profit=5.0,
            )
        )
        service = build_service(fake)
        for _ in range(3):
            await service.summary(
                start=date(2026, 10, 12),
                end=date(2026, 10, 12),
            )
            await service.daily(
                start=date(2026, 10, 12),
                end=date(2026, 10, 12),
            )
            await service.trades(
                start=date(2026, 10, 12),
                end=date(2026, 10, 12),
            )

        assert "order_send" not in fake.call_names()

    async def test_timezone_currency_and_rounding_are_stable(self):
        fake = FakeMT5()
        fake.deals.extend(
            closed_trade(
                1501,
                entry_utc=ist_moment(2026, 10, 12, 9, 0),
                exit_utc=ist_moment(2026, 10, 12, 9, 30),
                profit=1 / 3,
            )
        )
        service = build_service(fake)

        summary = await service.summary(
            start=date(2026, 10, 12),
            end=date(2026, 10, 12),
        )

        assert summary.reporting_timezone == "Asia/Kolkata"
        assert summary.broker_time_offset_seconds == SERVER_OFFSET
        assert summary.account_currency == "USD"
        # Values are rounded to two decimals for display.
        assert summary.gross_pnl == 0.33
        assert round(summary.gross_pnl, 2) == summary.gross_pnl


# ----------------------------------------------------------------------
# API surface
# ----------------------------------------------------------------------
class TestPerformanceApi:
    def test_summary_endpoint_is_read_only_and_shapes_the_contract(self, make_settings):
        from fastapi.testclient import TestClient

        from app.main import create_app

        fake = FakeMT5()
        fake.deals.extend(
            closed_trade(
                1601,
                entry_utc=ist_moment(2026, 10, 12, 9, 0),
                exit_utc=ist_moment(2026, 10, 12, 9, 30),
                profit=5.0,
            )
        )
        app = create_app(
            make_settings(report_timezone="Asia/Kolkata"), mt5_module=fake
        )

        with TestClient(app) as client:
            response = client.get(
                "/api/performance/summary",
                params={"start": "2026-10-12", "end": "2026-10-12"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["data_available"] is True
            assert body["closed_trades"] == 1
            assert body["net_pnl"] == 4.0
            assert body["reporting_timezone"] == "Asia/Kolkata"
            assert body["account_currency"] == "USD"
            assert body["accounting_rule"]

            daily = client.get(
                "/api/performance/daily",
                params={"start": "2026-10-12", "end": "2026-10-12"},
            )
            assert daily.status_code == 200
            daily_body = daily.json()
            assert daily_body["days"][0]["net_pnl"] == 4.0
            assert daily_body["totals"]["closed_trades"] == 1

            trades = client.get(
                "/api/performance/trades",
                params={"start": "2026-10-12", "end": "2026-10-12"},
            )
            assert trades.status_code == 200
            trades_body = trades.json()
            assert trades_body["count"] == 1
            assert trades_body["trades"][0]["position_id"] == 1601

            # No mutating request ever reached the terminal.
            assert "order_send" not in fake.call_names()

    def test_direction_filter_is_validated(self, make_settings):
        from fastapi.testclient import TestClient

        from app.main import create_app

        app = create_app(make_settings(), mt5_module=FakeMT5())
        with TestClient(app) as client:
            response = client.get(
                "/api/performance/summary",
                params={"direction": "sideways"},
            )
            assert response.status_code == 422
