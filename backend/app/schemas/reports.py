"""Read-only report schemas.

These mirror what :mod:`app.reports.service` reads back from disk. They are
descriptive only: no request body exists because the whole surface is read-only,
and nothing here can trigger a simulation run.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ReportRunOut(BaseModel):
    """Provenance metadata for one previously written report run."""

    model_config = ConfigDict(extra="ignore")

    run_id: str
    report_type: str
    generated_at_utc: Optional[datetime] = None
    generated_at_ist: Optional[datetime] = None
    symbol: Optional[str] = None
    requested_start_utc: Optional[datetime] = None
    requested_end_utc: Optional[datetime] = None
    timeframes: list[str] = Field(default_factory=list)
    timeframe_count: Optional[int] = None
    strategy_fingerprint: Optional[str] = None
    output_dir: str
    files: list[str] = Field(default_factory=list)
    summary_available: bool = False


class ReportsOut(BaseModel):
    """``GET /api/reports`` payload."""

    model_config = ConfigDict(extra="ignore")

    reports_root: str
    available: bool
    count: int = 0
    read_only: bool = True
    trading_enabled: bool = False
    runs: list[ReportRunOut] = Field(default_factory=list)


class ReportDetailOut(ReportRunOut):
    """One run's metadata plus its fully parsed summary."""

    model_config = ConfigDict(extra="ignore")

    summary_file: Optional[str] = None
    summary: Optional[dict[str, Any]] = None


__all__ = ["ReportDetailOut", "ReportRunOut", "ReportsOut"]
