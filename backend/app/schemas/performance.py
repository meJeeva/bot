"""Schemas for read-only MT5 trading-performance reporting.

The summary answers one question per field: *what did the account actually
realize?* Every amount is computed from MT5 deal history - never from the
dashboard's local records, never fabricated. When history cannot be read the
responses carry ``data_available: false`` plus the reason, and never zeros
pretending to be a quiet trading day.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

Direction = Literal["buy", "sell"]


class PerformanceCosts(BaseModel):
    """Signed trading costs as booked by MT5 (costs are normally <= 0)."""

    commission: float = 0.0
    swap: float = 0.0
    fee: float = 0.0
    total: float = 0.0


class FloatingPnl(BaseModel):
    """Open-position floating result, always reported separately from realized."""

    open_positions: int = 0
    profit: float = 0.0
    swap: float = 0.0
    total: float = 0.0


class CashMovement(BaseModel):
    """One non-trading account cash movement (deposit, credit, correction…)."""

    ticket: int
    type_code: int
    type_name: str
    time: datetime | None = None
    amount: float
    comment: str | None = None


class PerformanceFilters(BaseModel):
    """The filters a response was computed with (echoed for transparency)."""

    preset: str | None = None
    start: date | None = None
    end: date | None = None
    symbol: str | None = None
    direction: Direction | None = None
    magic: int | None = None


class PerformanceSummary(BaseModel):
    """Period summary: realized result, floating result, costs, cash movements."""

    data_available: bool
    error: str | None = None

    range_start: date
    range_end: date
    reporting_timezone: str
    broker_time_offset_seconds: int | None = None
    time_convention: str = "broker_server_local"
    account_currency: str | None = None

    balance: float | None = None
    equity: float | None = None

    closed_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float | None = None

    gross_pnl: float = 0.0
    costs: PerformanceCosts = Field(default_factory=PerformanceCosts)
    net_pnl: float = 0.0

    floating: FloatingPnl = Field(default_factory=FloatingPnl)

    cash_movements: list[CashMovement] = Field(default_factory=list)
    cash_movements_total: float = 0.0

    deals_checked: int = 0
    positions_matched: int = 0

    filters: PerformanceFilters = Field(default_factory=PerformanceFilters)
    accounting_rule: str
    generated_at: datetime


class DailyPerformanceItem(BaseModel):
    """One reporting day: closed trades attributed by their close time."""

    date: date
    closed_trades: int = 0
    wins: int = 0
    losses: int = 0
    gross_pnl: float = 0.0
    costs: PerformanceCosts = Field(default_factory=PerformanceCosts)
    net_pnl: float = 0.0
    win_rate: float | None = None


class DailyPerformanceResponse(BaseModel):
    data_available: bool
    error: str | None = None

    range_start: date
    range_end: date
    reporting_timezone: str
    account_currency: str | None = None

    days: list[DailyPerformanceItem] = Field(default_factory=list)
    totals: DailyPerformanceItem | None = None

    filters: PerformanceFilters = Field(default_factory=PerformanceFilters)
    generated_at: datetime


class PerformanceTrade(BaseModel):
    """One completed trade: the full deal lifecycle of one position identifier."""

    position_id: int
    symbol: str | None = None
    direction: Direction | None = None
    magic: int | None = None
    comment: str | None = None

    opened_volume: float = 0.0
    closed_volume: float = 0.0
    entry_time: datetime | None = None
    exit_time: datetime | None = None
    entry_price: float | None = None
    exit_price: float | None = None

    gross_pnl: float = 0.0
    costs: PerformanceCosts = Field(default_factory=PerformanceCosts)
    net_pnl: float = 0.0

    deal_tickets: list[int] = Field(default_factory=list)
    order_tickets: list[int] = Field(default_factory=list)
    close_day: date | None = None


class PerformanceTradesResponse(BaseModel):
    data_available: bool
    error: str | None = None

    reporting_timezone: str
    account_currency: str | None = None

    trades: list[PerformanceTrade] = Field(default_factory=list)
    count: int = 0

    filters: PerformanceFilters = Field(default_factory=PerformanceFilters)
    generated_at: datetime
