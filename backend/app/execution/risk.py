"""Risk engine (Phase 4): policy, position sizing and account-level limits.

Design rules encoded here:

* **Broker-calculated loss.** Estimated loss per lot comes from the broker's
  own profit calculator (``mt5.order_calc_profit``), never from a hardcoded
  pip value or lot multiplier. Tick metadata is only a diagnostic cross-check:
  brokers can report tick values inconsistent with their own P&L math (this
  was observed live during development), and sizing must follow the
  authoritative facility.
* **Round down, then re-verify.** Volume is floored to the broker step and
  the resulting loss is recomputed with the broker facility; if it still
  exceeds the budget, the trade is rejected - not "approximately" accepted.
* **Most restrictive limit wins.** The per-trade budget is simultaneously
  capped by the per-trade policy, the remaining aggregate exposure capacity
  and the remaining daily capacity.
* **Missing is not zero.** Unavailable metadata produces an explicit
  machine-readable rejection reason, never a silent 0 that could authorize.
* **Persistent protections.** Daily baselines, the high-water mark and
  lockouts live in the database and survive restarts; a restart never resets
  them, and the high-water mark only moves upward.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from ..config import Settings
from ..schemas.execution import RiskAssessment
from ..schemas.market import Quote
from ..storage import StatusStore

# (symbol, direction, volume, entry, exit) -> account-currency P&L (signed).
ProfitCalculator = Callable[[str, str, float, float, float], Optional[float]]
# (symbol, direction, volume, price) -> required margin in account currency.
MarginCalculator = Callable[[str, str, float, float], Optional[float]]

_EPS = 1e-9

# SYMBOL_TRADE_MODE values as reported by the terminal.
_TRADE_MODE_DISABLED = 0
_TRADE_MODE_LONG_ONLY = 1
_TRADE_MODE_SHORT_ONLY = 2
_TRADE_MODE_CLOSE_ONLY = 3
_TRADE_MODE_FULL = 4


# ======================================================================
# Inputs
# ======================================================================
@dataclass(frozen=True)
class SymbolSpec:
    """Broker trade metadata for one symbol, read fresh at decision time."""

    name: str
    digits: int
    point: float
    trade_mode: int | None
    contract_size: float | None
    tick_size: float | None
    tick_value_loss: float | None
    currency_profit: str | None
    volume_step: float | None
    volume_min: float | None
    volume_max: float | None
    volume_limit: float | None
    stops_level: int | None
    freeze_level: int | None
    filling_mode: int | None

    def metadata_problems(self) -> list[str]:
        """Structural problems that must block sizing (fail closed)."""
        problems: list[str] = []

        def _positive(value: float | None) -> bool:
            return value is not None and math.isfinite(value) and value > 0

        if not _positive(self.contract_size):
            problems.append("contract_size_invalid")
        if not _positive(self.tick_size):
            problems.append("tick_size_invalid")
        if not _positive(self.volume_step):
            problems.append("volume_step_invalid")
        if self.volume_min is None or not math.isfinite(self.volume_min) or self.volume_min < 0:
            problems.append("volume_min_invalid")
        if self.volume_max is None or not math.isfinite(self.volume_max) or self.volume_max <= 0:
            problems.append("volume_max_invalid")
        elif self.volume_min is not None and self.volume_max < self.volume_min:
            problems.append("volume_range_invalid")
        if not (self.currency_profit or "").strip():
            problems.append("profit_currency_unavailable")
        if self.point is None or not math.isfinite(self.point) or self.point <= 0:
            problems.append("point_invalid")
        return problems


@dataclass(frozen=True)
class RiskPolicy:
    """Validated risk policy with explicit units, built from Settings."""

    risk_per_trade_percent: float
    max_risk_per_trade_percent: float
    max_aggregate_risk_percent: float
    max_open_positions: int
    max_daily_loss_percent: float
    max_daily_drawdown_percent: float
    max_consecutive_losses: int | None
    cost_allowance_percent: float
    min_stop_distance_points: float
    max_stop_distance_points: float
    max_quote_age_seconds: float
    max_signal_age_minutes: float
    max_spread_points: float
    max_price_drift_points: float
    tp_policy: str
    fixed_rr: float
    allowed_symbols: tuple[str, ...]
    allowed_timeframes: tuple[str, ...]
    block_on_external_positions: bool
    daily_reset: str
    magic_number: int
    filling_policy: str

    @classmethod
    def from_settings(cls, settings: Settings) -> "RiskPolicy":
        return cls(
            risk_per_trade_percent=settings.execution_risk_per_trade_percent,
            max_risk_per_trade_percent=settings.execution_max_risk_per_trade_percent,
            max_aggregate_risk_percent=settings.execution_max_aggregate_risk_percent,
            max_open_positions=settings.execution_max_open_positions,
            max_daily_loss_percent=settings.execution_max_daily_loss_percent,
            max_daily_drawdown_percent=settings.execution_max_daily_drawdown_percent,
            max_consecutive_losses=settings.execution_max_consecutive_losses,
            cost_allowance_percent=settings.execution_cost_allowance_percent,
            min_stop_distance_points=settings.execution_min_stop_distance_points,
            max_stop_distance_points=settings.execution_max_stop_distance_points,
            max_quote_age_seconds=settings.execution_max_quote_age_seconds,
            max_signal_age_minutes=settings.execution_max_signal_age_minutes,
            max_spread_points=settings.execution_max_spread_points,
            max_price_drift_points=settings.execution_max_price_drift_points,
            tp_policy=settings.execution_tp_policy,
            fixed_rr=settings.execution_fixed_rr,
            allowed_symbols=tuple(settings.execution_allowed_symbols_list),
            allowed_timeframes=tuple(settings.execution_allowed_timeframes_list),
            block_on_external_positions=settings.execution_block_on_external_positions,
            daily_reset=settings.execution_daily_reset,
            magic_number=settings.execution_magic_number,
            filling_policy=settings.execution_filling_policy,
        )

    @property
    def fingerprint(self) -> str:
        """Stable identifier of the risk configuration used for a decision."""
        payload = repr(
            (
                self.risk_per_trade_percent,
                self.max_risk_per_trade_percent,
                self.max_aggregate_risk_percent,
                self.max_open_positions,
                self.max_daily_loss_percent,
                self.max_daily_drawdown_percent,
                self.max_consecutive_losses,
                self.cost_allowance_percent,
                self.min_stop_distance_points,
                self.max_stop_distance_points,
                self.max_quote_age_seconds,
                self.max_signal_age_minutes,
                self.max_spread_points,
                self.max_price_drift_points,
                self.tp_policy,
                self.fixed_rr,
                self.allowed_symbols,
                self.allowed_timeframes,
                self.block_on_external_positions,
                self.daily_reset,
                self.magic_number,
                self.filling_policy,
            )
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:12]

    def limits_dict(self) -> dict[str, Any]:
        """The risk limits, safe to expose through the API (no identity)."""
        return {
            "risk_per_trade_percent": self.risk_per_trade_percent,
            "max_risk_per_trade_percent": self.max_risk_per_trade_percent,
            "max_aggregate_risk_percent": self.max_aggregate_risk_percent,
            "max_open_positions": self.max_open_positions,
            "max_daily_loss_percent": self.max_daily_loss_percent,
            "max_daily_drawdown_percent": self.max_daily_drawdown_percent,
            "max_consecutive_losses": self.max_consecutive_losses,
            "cost_allowance_percent": self.cost_allowance_percent,
            "min_stop_distance_points": self.min_stop_distance_points,
            "max_stop_distance_points": self.max_stop_distance_points,
            "max_quote_age_seconds": self.max_quote_age_seconds,
            "max_signal_age_minutes": self.max_signal_age_minutes,
            "max_spread_points": self.max_spread_points,
            "max_price_drift_points": self.max_price_drift_points,
            "tp_policy": self.tp_policy,
            "fixed_rr": self.fixed_rr,
            "allowed_symbols": list(self.allowed_symbols),
            "allowed_timeframes": list(self.allowed_timeframes),
            "block_on_external_positions": self.block_on_external_positions,
            "daily_reset": self.daily_reset,
            "filling_policy": self.filling_policy,
            "config_fingerprint": self.fingerprint,
        }


@dataclass(frozen=True)
class TradeIntent:
    """A candidate trade originating from the live Fibonacci engine only."""

    setup_id: str
    symbol: str
    timeframe: str
    direction: str  # "buy" | "sell"
    zone_lower: float | None
    zone_upper: float | None
    primary_level_price: float | None
    stop_loss: float | None          # the setup's invalidation boundary
    signal_time_utc: datetime
    confirmation_time_utc: datetime
    source: str = "live_strategy"


@dataclass(frozen=True)
class ExposureSnapshot:
    """Bot-managed and foreign exposure at decision time."""

    bot_positions: int = 0
    bot_open_risk: float = 0.0
    bot_positions_missing_stop: int = 0
    pending_bot_orders: int = 0
    pending_bot_risk: float = 0.0
    external_positions: int = 0
    external_symbols: tuple[str, ...] = ()
    unresolved: bool = False


@dataclass(frozen=True)
class DailyRiskSnapshot:
    """Daily loss / drawdown posture computed from persisted state."""

    risk_date: str | None
    baseline_equity: float | None
    current_equity: float | None
    daily_loss: float
    daily_loss_limit: float
    high_water_equity: float | None
    drawdown: float
    drawdown_limit: float
    consecutive_losses: int
    lockout_reason: str | None
    baseline_available: bool


# ======================================================================
# Position sizing (pure, hand-verifiable)
# ======================================================================
@dataclass(frozen=True)
class SizingResult:
    volume: float
    estimated_loss: float
    loss_per_lot: float
    estimated_margin: float | None
    warnings: tuple[str, ...]


def floor_to_step(value: float, step: float) -> float:
    """Round *down* to the nearest broker volume step (never upward)."""
    if step <= 0:  # pragma: no cover - guarded by metadata validation
        raise ValueError("volume step must be positive")
    steps = math.floor((value / step) + 1e-9)
    return round(max(0.0, steps) * step, 10)


def size_position(
    *,
    budget: float,
    direction: str,
    entry: float,
    stop_loss: float,
    spec: SymbolSpec,
    calc_profit: ProfitCalculator,
    calc_margin: MarginCalculator | None = None,
    margin_free: float | None = None,
    allowance_percent: float = 0.0,
    take_profit: float | None = None,
) -> tuple[Optional[SizingResult], list[str], list[str]]:
    """Compute a broker-valid volume within ``budget``.

    Returns ``(result_or_None, reasons, warnings)``. A ``None`` result always
    comes with at least one machine-readable reason - missing data never
    silently becomes zero.
    """
    reasons: list[str] = []
    warnings: list[str] = []

    problems = spec.metadata_problems()
    if problems:
        return None, problems, warnings
    if not (math.isfinite(budget) and budget > 0):
        return None, ["risk_budget_invalid"], warnings
    if not (math.isfinite(entry) and entry > 0 and math.isfinite(stop_loss) and stop_loss > 0):
        return None, ["entry_or_stop_invalid"], warnings

    # --- authoritative loss per lot from the broker's own P&L facility ----
    raw_per_lot = calc_profit(spec.name, direction, 1.0, entry, stop_loss)
    if raw_per_lot is None or not math.isfinite(raw_per_lot):
        return None, ["loss_calculation_unavailable"], warnings
    # Signed P&L for the protective stop must be a finite loss; anything
    # else (0, positive, NaN) means the calculation is unusable.
    loss_per_lot = -float(raw_per_lot)
    if not (loss_per_lot > 0):
        return None, ["loss_calculation_unavailable"], warnings

    # --- diagnostic cross-check: tick metadata vs broker P&L --------------
    tick_size = spec.tick_size or 0.0
    tick_value = spec.tick_value_loss
    if tick_size > 0 and tick_value is not None and math.isfinite(tick_value) and tick_value > 0:
        tick_math = (abs(entry - stop_loss) / tick_size) * tick_value
        if tick_math > 0 and abs(tick_math - loss_per_lot) > 0.05 * loss_per_lot:
            warnings.append("tick_value_metadata_inconsistent_with_broker_pnl")

    # --- budget after the commission/slippage allowance -------------------
    effective_budget = budget * (1.0 - allowance_percent / 100.0)
    if not (math.isfinite(effective_budget) and effective_budget > 0):
        return None, ["risk_budget_exhausted_by_allowance"], warnings

    # --- volume, rounded DOWN to the broker step --------------------------
    step = float(spec.volume_step)
    volume = floor_to_step(effective_budget / loss_per_lot, step)

    volume_min = float(spec.volume_min or 0.0)
    volume_max = float(spec.volume_max or 0.0)
    volume_limit = float(spec.volume_limit or 0.0)

    if volume < volume_min:
        return None, ["min_volume_exceeds_risk_budget"], warnings

    volume = min(volume, volume_max)
    if volume_limit > 0:
        volume = min(volume, volume_limit)
    volume = floor_to_step(volume, step)
    if volume <= 0:  # pragma: no cover - defensive
        return None, ["min_volume_exceeds_risk_budget"], warnings

    # --- re-verify the loss AFTER rounding --------------------------------
    raw_loss = calc_profit(spec.name, direction, volume, entry, stop_loss)
    if raw_loss is None or not math.isfinite(raw_loss):
        return None, ["loss_calculation_unavailable"], warnings
    estimated_loss = -float(raw_loss)
    if not (estimated_loss > 0):
        return None, ["loss_calculation_unavailable"], warnings

    expected = loss_per_lot * volume
    if abs(estimated_loss - expected) > max(0.02, 0.05 * expected):
        # The broker's own math disagrees with itself across volumes: refuse
        # to trade on an ambiguous calculation.
        return None, ["loss_calculation_inconsistent"], warnings
    if estimated_loss > effective_budget + _EPS:
        return None, ["rounded_loss_exceeds_budget"], warnings

    # --- margin (estimated when the broker can compute it) ----------------
    estimated_margin: float | None = None
    if calc_margin is not None:
        margin = calc_margin(spec.name, direction, volume, entry)
        if margin is None or not math.isfinite(margin) or margin < 0:
            warnings.append("margin_estimate_unavailable")
        else:
            estimated_margin = float(margin)
            if margin_free is not None and math.isfinite(margin_free) and margin > margin_free:
                return None, ["insufficient_margin"], warnings

    # --- optional take-profit reward estimate -----------------------------
    if take_profit is not None:
        reward_raw = calc_profit(spec.name, direction, volume, entry, take_profit)
        if reward_raw is None or not math.isfinite(reward_raw) or reward_raw <= 0:
            warnings.append("take_profit_reward_unavailable")
        else:
            rr = float(reward_raw) / estimated_loss
            if math.isfinite(rr):
                warnings.append(f"reward_risk_ratio:{rr:.4f}")

    return (
        SizingResult(
            volume=volume,
            estimated_loss=estimated_loss,
            loss_per_lot=loss_per_lot,
            estimated_margin=estimated_margin,
            warnings=tuple(warnings),
        ),
        reasons,
        warnings,
    )


# ======================================================================
# Persistent risk state
# ======================================================================
class RiskStateTracker:
    """Daily baseline, high-water mark and lockouts - durable across restarts.

    Conventions (documented behavior):

    * **Daily baseline**: account equity at the first observation of the risk
      date. ``daily_loss = max(0, baseline_equity - equity)`` so realized and
      floating P&L both count. Deposits increase equity and therefore reduce
      the reported daily loss; withdrawals do the opposite (conservative).
    * **Reset boundary**: broker server midnight (default) using the measured
      server-clock offset, or a fixed UTC midnight - configurable and tested
      across timezone boundaries.
    * **Drawdown high-water mark**: persisted, and *never* reset by a restart
      or a day rollover; it only moves upward (or through the explicit
      authorized recovery), so protection cannot be bypassed by restarting.
    * **Lockouts persist**: a daily lockout clears only when the risk date
      rolls; a drawdown lockout clears only through the explicit recovery
      operation, and immediately re-engages if the condition still holds.
    """

    KEY = "global"

    def __init__(self, store: Optional[StatusStore], settings: Settings) -> None:
        self._store = store
        self._settings = settings
        self._row: dict[str, Any] | None = None
        if store is not None and store.enabled:
            self._row = store.get_execution_risk_state(self.KEY)

    # ---------------------------------------------------------------- read
    @property
    def available(self) -> bool:
        return self._store is not None and self._store.enabled

    @property
    def risk_date(self) -> str | None:
        return self._row.get("risk_date") if self._row else None

    @property
    def lockout_reason(self) -> str | None:
        return self._row.get("lockout_reason") if self._row else None

    @property
    def consecutive_losses(self) -> int:
        return int((self._row or {}).get("consecutive_losses") or 0)

    @property
    def last_reconciled_at(self) -> datetime | None:
        raw = (self._row or {}).get("last_reconciled_at")
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:  # pragma: no cover - defensive
            return None

    def risk_date_for(self, now: datetime, server_offset_seconds: int | None) -> str:
        """The risk window ``now`` belongs to, per the configured boundary."""
        if self._settings.execution_daily_reset == "utc_midnight" or not server_offset_seconds:
            local = now
        else:
            local = now + timedelta(seconds=server_offset_seconds)
        return local.strftime("%Y-%m-%d")

    # --------------------------------------------------------------- write
    def _persist(self) -> None:
        if self._store is None or not self._store.enabled or self._row is None:
            return
        self._store.save_execution_risk_state(self._row)

    def sync(
        self,
        *,
        equity: float,
        balance: float,
        now: datetime,
        server_offset_seconds: int | None,
    ) -> None:
        """Rollover the daily window if needed; advance the high-water mark."""
        if self._store is None or not self._store.enabled:
            self._row = None
            return
        date = self.risk_date_for(now, server_offset_seconds)
        if self._row is None:
            self._row = {
                "key": self.KEY,
                "risk_date": date,
                "baseline_equity": float(equity),
                "baseline_balance": float(balance),
                "high_water_equity": float(equity),
                "lockout_reason": None,
                "lockout_at": None,
                "consecutive_losses": 0,
                "last_reconciled_at": None,
                "updated_at": now.isoformat(),
            }
            self._persist()
            return

        changed = False
        if self._row.get("risk_date") != date:
            # Daily rollover: new baseline; the daily lockout and the daily
            # consecutive-loss counter reset. The drawdown high-water mark and
            # its lockout deliberately survive.
            self._row["risk_date"] = date
            self._row["baseline_equity"] = float(equity)
            self._row["baseline_balance"] = float(balance)
            if self._row.get("lockout_reason") == "daily_loss_lockout":
                self._row["lockout_reason"] = None
                self._row["lockout_at"] = None
            self._row["consecutive_losses"] = 0
            changed = True

        hwm = float(self._row.get("high_water_equity") or 0.0)
        if math.isfinite(equity) and equity > hwm:
            self._row["high_water_equity"] = float(equity)
            changed = True

        if changed:
            self._row["updated_at"] = now.isoformat()
            self._persist()

    def snapshot(
        self, *, equity: float, daily_loss_limit_percent: float, drawdown_limit_percent: float
    ) -> DailyRiskSnapshot:
        row = self._row or {}
        baseline = row.get("baseline_equity")
        hwm = row.get("high_water_equity")
        baseline_available = baseline is not None and math.isfinite(float(baseline))
        daily_loss = max(0.0, float(baseline) - equity) if baseline_available else 0.0
        daily_limit = (
            float(baseline) * daily_loss_limit_percent / 100.0
            if baseline_available
            else 0.0
        )
        hwm_value = (
            float(hwm) if hwm is not None and math.isfinite(float(hwm)) else None
        )
        drawdown = max(0.0, hwm_value - equity) if hwm_value is not None else 0.0
        drawdown_limit = (
            hwm_value * drawdown_limit_percent / 100.0 if hwm_value is not None else 0.0
        )
        return DailyRiskSnapshot(
            risk_date=row.get("risk_date"),
            baseline_equity=float(baseline) if baseline_available else None,
            current_equity=equity,
            daily_loss=daily_loss,
            daily_loss_limit=daily_limit,
            high_water_equity=hwm_value,
            drawdown=drawdown,
            drawdown_limit=drawdown_limit,
            consecutive_losses=self.consecutive_losses,
            lockout_reason=row.get("lockout_reason"),
            baseline_available=baseline_available,
        )

    def set_lockout(self, reason: str, now: datetime) -> None:
        if self._row is None:
            return
        if self._row.get("lockout_reason") != reason:
            self._row["lockout_reason"] = reason
            self._row["lockout_at"] = now.isoformat()
            self._row["updated_at"] = now.isoformat()
            self._persist()

    def clear_lockout(self, now: datetime, *, allowed: tuple[str, ...]) -> bool:
        """Explicit recovery; refuses to clear a reason outside ``allowed``."""
        if self._row is None:
            return False
        current = self._row.get("lockout_reason")
        if current is None or current not in allowed:
            return False
        self._row["lockout_reason"] = None
        self._row["lockout_at"] = None
        self._row["updated_at"] = now.isoformat()
        self._persist()
        return True

    def record_consecutive_losses(self, count: int, now: datetime) -> None:
        if self._row is None:
            return
        if int(self._row.get("consecutive_losses") or 0) != int(count):
            self._row["consecutive_losses"] = int(count)
            self._row["updated_at"] = now.isoformat()
            self._persist()

    def mark_reconciled(self, now: datetime) -> None:
        if self._row is None:
            return
        self._row["last_reconciled_at"] = now.isoformat()
        self._row["updated_at"] = now.isoformat()
        self._persist()


# ======================================================================
# Risk assessment
# ======================================================================
class RiskEngine:
    """Produces the typed :class:`RiskAssessment` for one candidate trade."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.policy = RiskPolicy.from_settings(settings)

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _finite(value: Any) -> bool:
        try:
            return value is not None and math.isfinite(float(value))
        except (TypeError, ValueError):
            return False

    def _budget(
        self,
        equity: float,
        exposure: ExposureSnapshot,
        daily: DailyRiskSnapshot,
    ) -> tuple[float, dict[str, float], list[str]]:
        """Most restrictive permitted monetary risk + why."""
        reasons: list[str] = []
        per_trade = min(
            equity * self.policy.risk_per_trade_percent / 100.0,
            equity * self.policy.max_risk_per_trade_percent / 100.0,
        )
        aggregate_limit = equity * self.policy.max_aggregate_risk_percent / 100.0
        aggregate_used = exposure.bot_open_risk + exposure.pending_bot_risk
        aggregate_remaining = aggregate_limit - aggregate_used
        daily_remaining = daily.daily_loss_limit - daily.daily_loss

        if aggregate_remaining <= 0:
            reasons.append("aggregate_risk_exhausted")
        if daily_remaining <= 0:
            reasons.append("daily_capacity_exhausted")

        budget = max(0.0, min(per_trade, aggregate_remaining, daily_remaining))
        breakdown = {
            "per_trade_cap": round(per_trade, 2),
            "aggregate_limit": round(aggregate_limit, 2),
            "aggregate_used": round(aggregate_used, 2),
            "aggregate_remaining": round(max(0.0, aggregate_remaining), 2),
            "daily_limit": round(daily.daily_loss_limit, 2),
            "daily_used": round(daily.daily_loss, 2),
            "daily_remaining": round(max(0.0, daily_remaining), 2),
        }
        return budget, breakdown, reasons

    def take_profit_for(
        self, *, direction: str, entry: float, stop_loss: float, spec: SymbolSpec
    ) -> tuple[Optional[float], list[str]]:
        """Configured take-profit policy. ``none`` => no TP, ever."""
        if self.policy.tp_policy != "fixed_rr":
            return None, []
        distance = abs(entry - stop_loss)
        reward = distance * self.policy.fixed_rr
        raw = entry + reward if direction == "buy" else entry - reward
        digits = max(0, int(spec.digits or 0))
        tp = round(raw, digits)
        if direction == "buy" and tp <= entry:
            return None, ["take_profit_invalid"]
        if direction == "sell" and tp >= entry:
            return None, ["take_profit_invalid"]
        return tp, []

    # ------------------------------------------------------------- assess
    def assess(
        self,
        intent: TradeIntent,
        *,
        account_equity: float,
        account_currency: str | None,
        account_margin_free: float | None,
        symbol: SymbolSpec,
        quote: Optional[Quote],
        exposure: ExposureSnapshot,
        daily: DailyRiskSnapshot,
        calc_profit: ProfitCalculator,
        calc_margin: MarginCalculator | None = None,
        now: Optional[datetime] = None,
    ) -> RiskAssessment:
        """Run every risk check; every failure contributes a reason code."""
        now = now or datetime.now(timezone.utc)
        reasons: list[str] = []
        warnings: list[str] = []

        entry: float | None = None
        stop_loss: float | None = None
        budget: float | None = None
        breakdown: dict[str, float] = {}
        estimated_loss: float | None = None
        volume: float | None = None
        take_profit: float | None = None
        stop_points: float | None = None
        reward_risk: float | None = None
        margin: float | None = None
        quote_age: float | None = None
        spread: float | None = None

        # --- source and scope --------------------------------------------
        if intent.source != "live_strategy":
            reasons.append("signal_not_live_strategy")
        if intent.symbol.upper() not in self.policy.allowed_symbols:
            reasons.append("symbol_not_allowed")
        if intent.timeframe not in self.policy.allowed_timeframes:
            reasons.append("timeframe_not_allowed")
        if intent.direction not in ("buy", "sell"):
            reasons.append("direction_invalid")

        # --- signal freshness --------------------------------------------
        confirmation = intent.confirmation_time_utc
        if confirmation.tzinfo is None or not self._finite(confirmation.timestamp()):
            reasons.append("confirmation_timestamp_invalid")
        else:
            age = now - confirmation.astimezone(timezone.utc)
            if age < timedelta(minutes=-1):
                reasons.append("confirmation_timestamp_invalid")
            elif age > timedelta(minutes=self.policy.max_signal_age_minutes):
                reasons.append("signal_too_old")

        # --- quote ---------------------------------------------------------
        if quote is None:
            reasons.append("quote_unavailable")
        else:
            quote_age = quote.age_seconds
            spread = quote.spread_points
            price = quote.ask if intent.direction == "buy" else quote.bid
            if quote.is_stale or quote.freshness != "live":
                reasons.append("quote_stale")
            elif not self._finite(quote_age) or quote_age > self.policy.max_quote_age_seconds:
                reasons.append("quote_too_old")
            if not self._finite(spread) or spread < 0:
                reasons.append("spread_unavailable")
            elif spread > self.policy.max_spread_points:
                reasons.append("spread_too_high")
            if not self._finite(price) or float(price) <= 0:
                reasons.append("quote_invalid")
                price = None
            entry = float(price) if price is not None else None

        # --- account -------------------------------------------------------
        if not self._finite(account_equity) or float(account_equity) <= 0:
            reasons.append("account_equity_unavailable")
            equity = 0.0
        else:
            equity = float(account_equity)
        if not (account_currency or "").strip():
            reasons.append("account_currency_unavailable")
        if (account_currency or "") and (symbol.currency_profit or ""):
            if account_currency.strip().upper() != symbol.currency_profit.strip().upper():
                reasons.append("profit_currency_mismatch")

        # --- symbol tradeability ------------------------------------------
        mode = symbol.trade_mode
        if mode in (None, _TRADE_MODE_DISABLED, _TRADE_MODE_CLOSE_ONLY):
            reasons.append("symbol_trading_disabled")
        elif mode == _TRADE_MODE_LONG_ONLY and intent.direction == "sell":
            reasons.append("symbol_long_only")
        elif mode == _TRADE_MODE_SHORT_ONLY and intent.direction == "buy":
            reasons.append("symbol_short_only")
        for problem in symbol.metadata_problems():
            reasons.append(problem)

        # --- protective stop ----------------------------------------------
        stop_loss = intent.stop_loss
        if stop_loss is None or not self._finite(stop_loss) or float(stop_loss) <= 0:
            reasons.append("stop_loss_missing")
            stop_loss = None
        elif entry is None:
            reasons.append("entry_price_unavailable")
        else:
            if intent.direction == "buy" and not (float(stop_loss) < entry):
                reasons.append("stop_loss_wrong_side")
            if intent.direction == "sell" and not (float(stop_loss) > entry):
                reasons.append("stop_loss_wrong_side")

            distance = abs(entry - float(stop_loss))
            point = symbol.point or 0.0
            tick = symbol.tick_size or 0.0
            if point > 0:
                stop_points = distance / point
                if stop_points < self.policy.min_stop_distance_points:
                    reasons.append("stop_too_close")
                if stop_points > self.policy.max_stop_distance_points:
                    reasons.append("stop_too_far")
                stops_level = symbol.stops_level or 0
                if stops_level and stop_points < stops_level:
                    reasons.append("broker_min_stop_distance")
            if tick > 0:
                ticks = distance / tick
                if abs(ticks - round(ticks)) > 1e-6:
                    reasons.append("stop_not_tick_aligned")

            # --- price drift --------------------------------------------
            primary = intent.primary_level_price
            if not self._finite(primary) or float(primary) <= 0:
                reasons.append("primary_level_unavailable")
            elif point > 0:
                drift_points = abs(entry - float(primary)) / point
                if drift_points > self.policy.max_price_drift_points:
                    reasons.append("price_drifted_beyond_entry")

        # --- account-level limits -----------------------------------------
        if not daily.baseline_available:
            reasons.append("daily_baseline_unavailable")
        if daily.lockout_reason:
            reasons.append(daily.lockout_reason)
        if (
            self.policy.max_consecutive_losses is not None
            and daily.consecutive_losses >= self.policy.max_consecutive_losses
        ):
            reasons.append("consecutive_losses_lockout")
        if exposure.bot_positions_missing_stop > 0:
            reasons.append("bot_position_missing_stop")
        if exposure.unresolved:
            reasons.append("exposure_unresolved")
        if exposure.bot_positions + exposure.pending_bot_orders >= self.policy.max_open_positions:
            reasons.append("max_open_positions")
        if self.policy.block_on_external_positions and exposure.external_positions > 0:
            reasons.append("external_positions_present")

        # --- budget --------------------------------------------------------
        if equity > 0:
            budget, breakdown, budget_reasons = self._budget(equity, exposure, daily)
            reasons.extend(budget_reasons)

        # --- take-profit policy -------------------------------------------
        if not reasons and entry is not None and stop_loss is not None:
            take_profit, tp_reasons = self.take_profit_for(
                direction=intent.direction, entry=entry, stop_loss=float(stop_loss), spec=symbol
            )
            reasons.extend(tp_reasons)

        # --- sizing (only when everything else passed) --------------------
        if not reasons and budget is not None and entry is not None and stop_loss is not None:
            result, size_reasons, size_warnings = size_position(
                budget=budget,
                direction=intent.direction,
                entry=entry,
                stop_loss=float(stop_loss),
                spec=symbol,
                calc_profit=calc_profit,
                calc_margin=calc_margin,
                margin_free=account_margin_free,
                allowance_percent=self.policy.cost_allowance_percent,
                take_profit=take_profit,
            )
            reasons.extend(size_reasons)
            warnings.extend(size_warnings)
            if result is not None:
                volume = result.volume
                estimated_loss = result.estimated_loss
                margin = result.estimated_margin
                for warning in result.warnings:
                    if warning.startswith("reward_risk_ratio:"):
                        try:
                            reward_risk = float(warning.split(":", 1)[1])
                        except ValueError:  # pragma: no cover - defensive
                            reward_risk = None
                        warnings.append("reward_risk_ratio_available")
                    elif warning not in warnings:
                        warnings.append(warning)

        return RiskAssessment(
            allowed=not reasons,
            setup_id=intent.setup_id,
            symbol=intent.symbol,
            timeframe=intent.timeframe,
            direction=intent.direction if intent.direction in ("buy", "sell") else "buy",
            source=intent.source,
            risk_budget=round(budget, 2) if budget is not None else None,
            budget_breakdown=breakdown,
            estimated_loss=round(estimated_loss, 2) if estimated_loss is not None else None,
            proposed_volume=volume,
            entry_price=round(entry, 8) if entry is not None else None,
            stop_loss=round(float(stop_loss), 8) if stop_loss is not None else None,
            take_profit=round(take_profit, 8) if take_profit is not None else None,
            stop_distance_points=round(stop_points, 2) if stop_points is not None else None,
            reward_risk_ratio=round(reward_risk, 4) if reward_risk is not None else None,
            estimated_margin=round(margin, 2) if margin is not None else None,
            account_equity=round(equity, 2) if equity > 0 else None,
            account_currency=account_currency,
            quote_age_seconds=round(float(quote_age), 3)
            if self._finite(quote_age)
            else None,
            spread_points=round(float(spread), 2) if self._finite(spread) else None,
            reasons=reasons,
            warnings=warnings,
            config_fingerprint=self.policy.fingerprint,
            generated_at=now,
        )


def _now_utc() -> datetime:  # pragma: no cover - tiny convenience
    return datetime.now(timezone.utc)


__all__ = [
    "DailyRiskSnapshot",
    "ExposureSnapshot",
    "RiskAssessment",
    "RiskEngine",
    "RiskPolicy",
    "RiskStateTracker",
    "SizingResult",
    "SymbolSpec",
    "TradeIntent",
    "floor_to_step",
    "size_position",
]
