"""Schemas for automatic trading status and history."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class AutoTradingStatus(BaseModel):
    status: str = "STOPPED"
    auto_trading_status: str = "STOPPED"
    trading_status: str = "STOPPED"
    state: str = "STOPPED"

    symbol: str | None = None
    timeframe: str = "M1"
    connection_status: str | None = None
    terminal_connected: bool = False
    trading_enabled: bool = False

    balance: float | None = None
    equity: float | None = None

    position_status: str = "none"
    position_state: str = "none"
    position_ticket: int | None = None
    ticket: int | None = None
    entry_price: float | None = None
    entry_time: datetime | None = None
    current_profit: float | None = None
    profit: float | None = None
    unrealized_pnl: float | None = None

    last_entry_result: str | None = None
    last_exit_result: str | None = None

    next_cycle: datetime | None = None
    next_scheduled_cycle: datetime | None = None
    next_cycle_at: datetime | None = None

    completed_cycles: int = 0
    session_completed_cycles: int = 0
    cycles_completed: int = 0
    successful_entries: int = 0
    failed_entries: int = 0
    failed_exits: int = 0

    last_error: str | None = None
    error: str | None = None

    session_id: str | None = None
    cycle_id: str | None = None
    magic_number: int | None = None

    strategy_phase: str | None = None
    profile: str | None = None
    # Spread gate: `spread_blocked` is True while the live spread is above the
    # configured maximum. `strategy_phase == "SPREAD_BLOCKED"` means entries are
    # actually being withheld; an open position keeps its own phase.
    spread_blocked: bool = False
    spread_points: float | None = None
    max_spread_points: float | None = None
    active_side: str | None = None
    reference_value: float | None = None
    buy_entry: float | None = None
    buy_sl: float | None = None
    sell_entry: float | None = None
    sell_sl: float | None = None
    buy_order_ticket: int | None = None
    sell_order_ticket: int | None = None
    highest_favorable_price: float | None = None
    lowest_favorable_price: float | None = None
    break_even_active: bool = False
    break_even_level: float | None = None
    last_processed_deal: Any = None
    previous_cycle_complete: bool = False

    # Worker heartbeat and MT5 state reporting.
    worker_heartbeat: float | None = None
    heartbeat: float | None = None
    last_heartbeat: float | None = None
    mt5_connected: bool = False
    mt5_connectivity: bool = False
    mt5_query_ok: bool = True
    mt5_query_error: str | None = None
    pending_order_count: int = 0
    pending_orders: int = 0
    open_position_count: int = 0
    open_positions: int = 0
    last_order_attempt: str | None = None
    last_broker_result: str | None = None
    last_result: str | None = None
    active_profile: str | None = None

    def sync(self) -> "AutoTradingStatus":
        self.auto_trading_status = self.status
        self.trading_status = self.status
        self.state = self.status
        self.ticket = self.position_ticket
        self.profit = self.current_profit
        self.unrealized_pnl = self.current_profit
        self.cycles_completed = self.completed_cycles
        self.next_scheduled_cycle = self.next_cycle
        self.next_cycle_at = self.next_cycle
        self.error = self.last_error
        return self


class AutoTradingHistoryItem(BaseModel):
    cycle_id: str
    symbol: str | None = None
    entry_time: datetime | None = None
    exit_time: datetime | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    volume: float | None = None
    profit: float | None = None
    status: str = "unknown"
    error: str | None = None


class AutoTradingHistoryResponse(BaseModel):
    items: list[AutoTradingHistoryItem] = Field(default_factory=list)
    history: list[AutoTradingHistoryItem] = Field(default_factory=list)
    count: int = 0
