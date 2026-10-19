# Strategy research: Fibonacci vs trend-following pullback vs breakout-retest

Status: research capability **implemented** under `backend/app/backtest/research/`.
Trading behaviour unchanged: `APP_READ_ONLY=True`, `trading_enabled=False`,
execution disabled, no order-submission path added.

This document is the mandatory **audit and rule specification** produced before
implementation. It records exactly what exists, what the two new candidates do,
what data they need, what is assumed, and what is missing.

---

## 1. Repository audit (what exists and what is reusable)

| Area | Location | Reuse decision |
| --- | --- | --- |
| Fibonacci strategy engine | `app/strategy/` (`engine.py`, `swing.py`, `setup.py`, `confirmation.py`, `fibonacci.py`) | **Untouched.** Used only as the unchanged baseline. |
| Fibonacci live/replay setup store | `app/storage.py` | Untouched. Research never writes to it (`store=None`). |
| Historical candle pipeline | `app/mt5/market_data.py` (`read_candles_range`, `ServerClock`), `app/backtest/runner.py` (`read_candles_range_chunked`, `make_mt5_dataset_loader`, `connect_and_resolve`, `resolve_date_range`, `parse_timeframes`) | **Reused verbatim** by the research runner. |
| Dataset validation (completed candles only, no fabrication) | `app/replay/dataset.py` (`build_replay_dataset`) | **Reused verbatim.** |
| Lower-timeframe same-candle resolution | `app/backtest/intrabar.py` (`IntrabarResolver`) | **Reused verbatim.** |
| Fibonacci trade evaluator | `app/backtest/evaluator.py` (`BacktestEngine`) | **Reused verbatim** for the baseline leg of the comparison. |
| Exit-policy comparison conventions | `app/backtest/exit_comparison.py` (`compute_metrics`, cost model, OOS split) | **Pattern reused** (identical cost convention and OOS method). |
| Risk policy + sizing | `app/execution/risk.py` (`RiskPolicy`, `SymbolSpec`, `size_position`) | **Reused** for identical portfolio-risk limits and sizing maths. |
| Risk assessment gates | `app/execution/risk.py` (`RiskEngine.assess`) | **Not reused directly** — it is deliberately Fibonacci-only (`intent.source != "live_strategy"` is rejected). The research simulator mirrors the same `RiskPolicy` limits instead, so signals are never mislabelled as live strategy signals. |
| Phase-boundary guard | `app/../tests/test_phase_boundaries.py` | Must keep passing. Research code lives under `app/backtest/research/` (permitted for strategy vocabulary) and adds no order functions. |
| Reports | `reports/backtests/` (written by prior runs) | Read-only precedent; research writes to `reports/research/`. |

**Verified data availability.** The `MetaTrader5` Python package is importable and
a **demo** terminal (MetaQuotes-Demo, trade_mode 0) with `XAUUSD` is reachable from
this environment, so genuine historical intervals can be loaded. Each `Candle`
also carries `spread_points` (MT5's per-bar `spread` field), OI/tick volume, and a
measured broker-clock offset, so spread can be modelled from **measured per-bar
values** rather than assumed outright.

---

## 2. Baseline: existing Fibonacci strategy (unchanged)

Run through the existing `BacktestEngine` exactly as today:
confirming-candle-close entry, structural stop (invalidation boundary),
SL / invalidation / expiry / end-of-data exits, same `RiskPolicy`. No rule,
parameter, confirmation threshold or history is modified. The baseline leg is
produced by the **same** runner over the **same** intervals and cost model, so it
is directly comparable to the two candidates.

---

## 3. Candidate 2 — trend-following pullback (H1 context, M15 pullback, M5 trigger)

All conditions use **completed candles only**; higher-timeframe features use the
most recent bar that had already closed at the decision instant (no look-ahead).

Frozen parameters (not optimised): `H1_FAST=50`, `H1_SLOW=200`, `M15_FAST=20`,
`M15_SLOW=50`, `M5_FAST=20`, `STOP_LOOKBACK_M5=5`, `REWARD_RISK=2.0`,
`STOP_BUFFER_POINTS=20`.

1. **Directional context (H1, completed):** uptrend when `EMA50(H1) > EMA200(H1)`,
   downtrend when `EMA50(H1) < EMA200(H1)`. Otherwise no trade (gate).
2. **M15 pullback (completed):** for an uptrend, the latest closed M15 close is
   below `EMA20(M15)` but still above `EMA50(M15)` (a pullback inside the trend).
   Bearish mirrored. Otherwise no trade.
3. **M5 confirmation (completed):** the latest closed M5 candle is a reversal in
   the trend direction — bullish: `close > open` and `close > EMA20(M5)`; bearish
   mirrored. This is the trigger candle.
4. **Entry:** confirmation candle **close** (simulated; the confirming M5 candle
   has closed, so the next decision is actionable with no look-ahead).
5. **Stop:** long → `min(low of last 5 completed M5 candles) - buffer`;
   short → `max(high of last 5) + buffer`.
6. **Target:** `entry ± REWARD_RISK * |entry - stop|`.
7. **Exit:** target, stop, or an **H1 trend flip** at candle close, or
   end-of-data (marked, reported separately).

Rationale for objectivity: every condition is a plain comparison of a completed
bar's value against a moving average or a fixed level, so it is reproducible from
candles alone and unit-testable.

---

## 4. Candidate 3 — breakout-retest scalping (M5 range breakout + retest, no chasing)

Frozen parameters: `RANGE_LOOKBACK=20`, `MIN_RANGE_POINTS=50`,
`MAX_RANGE_POINTS=600`, `MAX_BREAKOUT_BODY_POINTS=250`,
`MAX_EXTENSION_POINTS=150`, `RETEST_MAX_CANDLES=8`, `STOP_BUFFER_POINTS=20`,
`MAX_HOLD_CANDLES=40`, `FALLBACK_RR=1.0`.

1. **Range (objective):** over the last `RANGE_LOOKBACK` completed M5 candles
   *before* the breakout candle, `range_high=max(high)`, `range_low=min(low)`.
   Require `MIN_RANGE_POINTS <= (range_high-range_low)/point <= MAX_RANGE_POINTS`.
2. **Breakout (completed):** a candle closes above `range_high` (long) or below
   `range_low` (short).
3. **No chasing:** the breakout candle's body `|close-open| <= MAX_BREAKOUT_BODY_POINTS`
   **and** its extension `close - range_high <= MAX_EXTENSION_POINTS` (long;
   mirrored for short). An extended breakout is rejected, not entered.
4. **Retest (completed, within `RETEST_MAX_CANDLES`):** a later M5 candle's range
   touches the boundary (`low <= range_high <= high` for long) **and** closes back
   on the breakout side (`close > range_high`).
5. **Entry:** the retest confirmation candle **close**.
6. **Stop:** long → `min(retest candle low, range_high) - buffer`; short mirrored.
7. **Target:** measured move `entry ± (range_high - range_low)`; if that is less
   than `FALLBACK_RR * risk`, use `entry ± FALLBACK_RR*risk` instead.
8. **Exit:** target, stop, or a **time stop** after `MAX_HOLD_CANDLES`, or
   end-of-data.

**Deferred:** range **mean reversion** is explicitly *not* implemented here and is
recorded as a separate future research candidate (see §9). It is not combined
into either candidate above.

---

## 5. Required data and intervals

* Symbol: `XAUUSD` (resolved exactly as the Fibonacci pipeline resolves it).
* Intervals: **M5** (decision timeframe for both candidates), **M15** and **H1**
  (context for candidate 2), **M1** (optional, only as intrabar evidence for
  same-candle stop/target ordering — never used as a signal input).
* A single, verified, chronological window shared by all three strategies so the
  primary backtests are comparable (default: the same window as the existing
  Fibonacci reports).
* Completed candles only; the still-forming bar is excluded by
  `build_replay_dataset`.

---

## 6. Assumptions (labelled, never presented as measurement)

* **Spread:** modelled from the **measured per-bar `spread_points`** at the entry
  and exit candles (a genuine MT5 field, but a per-bar value — an approximation,
  not a tick-level measurement). Primary cost: one full spread width per closed
  trade, `net = gross - cost_price * volume`, `cost_price = spread_price`.
* **Commission / swap / financing:** **not** reliably known → not measured. A
  commission assumption (default `0`) and a cost-sensitivity grid
  (`0, 0.10, 0.30, 0.50, 1.00` USD price units ≈ 0–100 points) are reported so
  the reader can see how results move.
* **Fills:** entry at the confirming candle's close; exits at the exact stop /
  target level, or the candle close for time/trend/EOD exits. Slippage is folded
  into the cost-sensitivity grid, not invented as a fixed number.
* **Same-candle stop & target:** stop presumed first (worst case) unless exact
  tiling **M1** bars prove the target came first (`IntrabarResolver`).
* **Sizing/risk:** identical `RiskPolicy` limits and `size_position` maths as the
  Fibonacci strategy; mark-to-market P&L via the same `default_calc_profit`.
* Position sizing ceiling, max open positions, daily-loss %, drawdown %,
  consecutive-loss lockout and stop-distance bounds are all enforced.
* No external/manual positions; the simulation is a single isolated account.

---

## 7. Missing information / limitations (prominent)

* **No tick or M1-exact spread series** across the whole window: cost is per-bar
  spread + an assumption grid, so profitability is *not* established by this
  alone.
* **Commission and swap are unknown** and omitted from the primary figure; the
  sensitivity grid bounds their effect only approximately.
* **Higher-timeframe alignment** uses completed-bar values; a strategy acting on
  M5 cannot know an H1 bar that has not closed — by design, this *removes* some
  signals rather than forward-looking.
* **Regime dependence:** a six-month sample is one regime; results do not
  generalise and no conclusion of superiority is drawn from in-sample profit or a
  small sample.
* **Correlated legs:** all three legs use identical risk limits per timeframe and
  run as independent accounts; no cross-strategy portfolio netting is modelled.

---

## 8. Chronological split and freeze policy

* Split by **entry time**: development 50% / validation 20% / out-of-sample 30%
  of the requested window (fractions configurable).
* Rule constants in §3–§4 are **frozen in code** before any window is evaluated.
  The out-of-sample block is evaluated once, after freezing; it is never used to
  re-tune a parameter. The split boundary and the frozen fingerprints are written
  into every report.

---

## 9. Deferred candidate — range mean reversion

Recorded, not implemented: fade the range edges of a clearly bounded, low-trend
regime with a reversion target and a stop beyond the range; requires an objective
"range regime" filter (e.g. ADX below a threshold and range width bounded) and a
documented invalidation. It is intentionally excluded from this implementation so
the first comparison stays limited to the two specified candidates plus the
Fibonacci baseline.

---

## 10. How to run (read-only)

```
cd backend
python -m app.backtest.research.cli --start 2026-04-14 --end 2026-10-14 \
    --timeframes M1,M5,M15,H1 --output-dir ../reports/research
```

Reports are written to `reports/research/<run_id>/`:
`fibonacci.json`, `trend_pullback.json`, `breakout_retest.json`,
`comparison_summary.json` + `*.csv`, and `README.md`. Nothing is overwritten:
each run gets its own timestamped/fingerprinted directory.

## 11. Safety

* No MetaTrader order-execution function is imported or called anywhere in the
  research path (`tests/test_phase_boundaries.py` continues to enforce this).
* The live Fibonacci engine, its configuration, confirmation history and the
  setup store are never touched by research code.
* Replay, shadow validation, simulated research trades and real broker orders
  remain distinctly labelled in every report (`read_only`, `trading_enabled`,
  `source`).
