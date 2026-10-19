"""Schemas for the recent connection-event log."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ConnectionEvent(BaseModel):
    """One persisted MT5 connection state transition."""

    timestamp: datetime
    state: str
    initialized: bool
    connected: bool
    account_type: str | None = None
    symbol: str | None = None
    error: str | None = None


class ConnectionEventsResponse(BaseModel):
    """``GET /api/mt5/events`` payload."""

    enabled: bool = Field(description="False when SQLite persistence is disabled.")
    total_events: int = 0
    total_snapshots: int = 0
    events: list[ConnectionEvent] = Field(default_factory=list)
    errors: list[ConnectionEvent] = Field(default_factory=list)
