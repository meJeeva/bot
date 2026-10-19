# Full-strategy historical backtest

Status: **implemented and run** under `backend/app/backtest/lab/`.
Trading behaviour unchanged: `APP_READ_ONLY=True`, `trading_enabled=False`,
execution disabled, no order-submission path. No strategy rule was modified.

This document is the data-quality, method, assumption and limitation record for
the backtest that measures the historical performance of **every implemented
strategy** over six months of genuine XAUUSD candles on a $10,000 account.

---

## 1. What is tested

The four strategies that genuinely exist in the repository, each run on its own
and then as a combined portfolio:

| # | Strategy | Module |
| --- | --- | --- |
| 1 | Fibonacci retracement | `app/strategy/fibonacci_signal.py` |
| 2 | EMA trend pullback | `app/strategy/ema_pullback.py` |
| 3 | Liquidity sweep + MSS + FVG | `app/strategy/liquidity_sweep_mss_fvg.py` |
| 4 | Session breakout and retest | `app/strategy/session_breakout_retest.py` |

All four are stateless functions of a candle prefix, and each is driven with the
repository's own configuration from `app/config.py` (mirroring
`StrategyCoordinator`). Nothing is re-implemented: the live `evaluate()` methods
are called directly.

**Note on documentation vs implementation.** `docs/ema_pullback_rules.md`
describes a *multi-timeframe* EMA pullback (H1 context / M15 pullback / M5
trigger), but the implemented `EmaPullbackStrategy` is **single-timeframe**: it
reads only the timeframe it is evaluated on. The implemented rule is what is
tested; the documentation discrepancy is reported rather than papered over.

No additional registered strategy was found beyond these four.

---

## 2. Data (verified, not assumed)

Genuine history is loaded from the running MetaTrader 5 terminal through the
existing replay pipeline (`make_mt5_dataset_loader` → `build_replay_dataset`).

| Timeframe | Bars | First (UTC) | Last (UTC) | Coverage |
| --- | --- | --- | --- | --- |
| M5 | 34,743 | 2026-04-14 | 2026-10-14 | full six months |
| M15 | 11,583 | 2026-04-14 | 2026-10-14 | full six months |
| M30 | 5,793 | 2026-04-14 | 2026-10-14 | full six months |
| H1 | 2,898 | 2026-04-14 | 2026-10-14 | full six months |
| H4 | 792 | 2026-04-14 | 2026-10-14 | full six months |
| D1 | 132 | 2026-04-14 | 2026-10-14 | full six months |
| M1 | ~98,508 | 2026-07-02 | 2026-10-14 | **partial (~3.5 months)** |

**The six timeframes with a full six months are M5, M15, M30, H1, H4 and D1.**
This was verified empirically from the terminal, not assumed. M1 does **not**
cover six months and is therefore **not** used as a decision timeframe; it is
loaded only as lower-timeframe evidence for same-candle stop/target ordering,
and the conservative rule applies wherever the M1 bars do not exactly tile the
decision candle.

Data-quality checks applied by the existing replay builder (reported per run in
`data_quality.json` and the summary's `data_notes`):

* chronological ordering (out-of-order bars are reported, then sorted);
* duplicate timestamps (identical duplicates dropped; conflicting duplicates
  refused as untrustworthy);
* still-forming bars excluded (only completed candles are replayed);
* OHLC integrity (`high >= max(open, close)`, `low <= min(open, close)`);
* interior gaps detected and reported (weekends/holidays), never filled with
  synthetic candles;
* coverage warnings when the terminal holds less history than requested.

No candle is fabricated and no missing interval is synthesised.

---

## 3. Method (no look-ahead)

* Signals come from the **actual confirmation engine** (`evaluate()`), one call
  per bar. The confirm bar has closed before the decision is made.
* Each strategy is handed a strictly **backward** window, so appending future
  candles cannot change a decision:
  * Fibonacci / EMA pullback - last 1,200 completed bars;
  * liquidity sweep - last 900 completed bars;
  * session breakout - the decision candle's own session day (or the minimum
    pre-check length when the candle sits outside the permitted window, where
    the strategy rejects on the session clock alone).
  * A bounded window only ever *removes older* history - it can never add a
    future bar. `tests/backtest/test_lab_adapters.py` proves the no-look-ahead
    property and shows the bounded window agrees with the full-prefix decision
    on >= 98% of bars (and is exact for the session strategy).
* Entry is simulated at the confirming candle's **close** (the first actionable
  price). Exits are tested from the **following** candle.
* Same-candle stop/target: the stop is presumed first **unless** exactly-tiling
  M1 bars prove the target came first.
* One signal produces at most one trade; a repeated setup id and a second open
  position on the same timeframe and direction are rejected
  (`duplicate_signal` / `duplicate_exposure`); the portfolio picks a
  deterministic winner on a same-bar conflict.

---

## 4. Account and risk scenarios

Initial equity **$10,000**, currency USD, leverage 100 (from the demo account).

* **Primary** - the repository's configured `RiskPolicy` unchanged: 0.5% risk per
  trade (2.0% cap), 5% aggregate risk, 3 open positions, 5% daily loss limit,
  10% daily drawdown, 4 entries per risk day, $10 daily profit stop, measured
  spread cost, `tp_policy=none`.
* **Conservative** (clearly labelled comparison) - 0.25% risk per trade, 1%
  daily loss limit, **1** open position, 4 entries per day, minimum planned
  reward/risk **1.5:1**, and the same $10 daily profit stop.

Both are reported side by side. The conservative scenario tightens only
account-level numbers; it never changes a strategy's stop, target or
confirmation rule. Both are configurable via `app/backtest/lab/scenarios.py`.

Position size uses the actual stop distance, the symbol's real contract
specifications (`point`, `contract_size`, `volume_min/step/max`, `stops_level`
from `symbol_info`) and the account currency - a fixed XAUUSD pip value is never
assumed.

---

## 5. Costs

Cost is the **measured per-bar spread** (MT5's rates `spread` field, in points)
converted once to price (`spread_price = points * point`), charged as ONE full
spread width per closed trade: `net = gross - spread_price * volume`.
Commission and swap have no broker specification and are therefore **not**
modelled; a cost-sensitivity grid is available in the existing research audit.
A live spread snapshot is never presented as a historical measurement.

---

## 6. Validation and overfitting protection

Trades are split by entry time: **development 60% / validation 20% /
out-of-sample 20%**. The strategy rules are frozen in code before evaluation and
the out-of-sample block is never used to tune a parameter. In-sample and
out-of-sample performance are reported separately with the trade count in each
split.

---

## 7. Safety

* No live or demo order placement: no order-execution function is imported or
  called, and `tests/test_phase_boundaries.py` enforces this.
* No strategy rule was changed; existing tests still pass.
* No hardcoded winning signals or invented performance values.

---

## 8. Deliverables (written to `reports/backtests/<run_id>/`)

`summary.json`, `comparison.csv`, `trades.csv` (complete ledger with timestamps,
strategy, timeframe, direction, entry, SL, TP, exit, costs, outcome, R-multiple
and balance after each trade), `data_quality.json`, `monthly_breakdown.csv`,
`timeframe_breakdown.csv`, `equity_curve.svg` (equity + drawdown), one
`<strategy>.json` per strategy, `portfolio.json`, and `README.md`.

The run directory is the one the existing read-only reports API and dashboard
panel already scan, so results appear in the existing backtest panel with no new
page.

## 9. Reproduce

```
cd backend
python -m app.backtest.lab.cli --start 2026-04-14 --end 2026-10-14 \
    --timeframes M5,M15,M30,H1,H4,D1 --start-equity 10000
```

Re-running with identical data and configuration reproduces the same run id and
the same results (the pipeline is deterministic).

---

## 10. Measured results (run `lab_xauusd_20260414_20261015_47c5d038`)

Window 2026-04-14 → 2026-10-14 UTC, XAUUSD, $10,000 start. Cost is the measured
per-bar spread. **Every leg is a net loss on this sample. No strategy is
declared profitable; the sample is one regime.**

### Primary scenario (repository defaults), full window

| Strategy | Signals | Approved | Closed | Win rate | PF | Expectancy $ | Net $ | Return % | Ending balance | Max DD $ | Max DD % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Fibonacci retracement | 644 | 346 | 346 | 0.251 | 0.879 | -4.30 | -1,486.70 | -14.87 | 8,513.30 | 1,962.71 | 19.63 |
| EMA trend pullback | 159 | 122 | 122 | 0.238 | 0.612 | -13.73 | -1,675.15 | -16.75 | 8,324.85 | 2,431.12 | 24.31 |
| Liquidity sweep + MSS + FVG | 1 | 1 | 1 | 0.000 | — | -50.22 | -50.22 | -0.50 | 9,949.78 | 50.22 | 0.50 |
| Session breakout + retest | 460 | 343 | 343 | 0.227 | 0.839 | -5.16 | -1,770.26 | -17.70 | 8,229.74 | 2,933.17 | 29.33 |
| **Combined portfolio** | 1,264 | 415 | 415 | 0.241 | 0.833 | -5.46 | -2,266.86 | -22.67 | 7,733.14 | 3,455.96 | 34.56 |

### Conservative scenario (0.25% risk, 1% daily loss, 1 position), full window

| Strategy | Signals | Approved | Closed | Win rate | PF | Net $ | Return % | Max DD % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Fibonacci retracement | 644 | 238 | 238 | 0.273 | 0.998 | -10.01 | -0.10 | 5.07 |
| EMA trend pullback | 159 | 96 | 96 | 0.240 | 0.619 | -677.53 | -6.78 | 9.81 |
| Liquidity sweep + MSS + FVG | 1 | 1 | 1 | 0.000 | — | -25.11 | -0.25 | 0.25 |
| Session breakout + retest | 460 | 235 | 235 | 0.221 | 0.724 | -1,179.86 | -11.80 | 12.14 |
| **Combined portfolio** | 1,264 | 317 | 317 | 0.227 | 0.791 | -1,186.05 | -11.86 | 14.72 |

### Chronological split, primary scenario (closed trades / win rate / PF / net $)

| Strategy | Development | Validation | Out-of-sample |
| --- | --- | --- | --- |
| Fibonacci | 222 / 0.257 / 0.901 / -790.75 | 67 / 0.269 / 0.936 / -142.02 | 57 / 0.211 / 0.727 / -553.94 |
| EMA pullback | 78 / 0.218 / 0.580 / -1,215.46 | 25 / 0.280 / 0.733 / -217.48 | 19 / 0.263 / 0.601 / -242.21 |
| Liquidity sweep | 1 / 0.00 / — / -50.22 | 0 / — / — / 0 | 0 / — / — / 0 |
| Session breakout | 205 / 0.176 / 0.634 / -2,531.89 | 67 / 0.358 / **1.519** / +909.18 | 71 / 0.254 / 0.936 / -147.55 |
| Portfolio | 258 / 0.225 / 0.753 / -2,203.39 | 76 / 0.303 / 1.080 / +170.81 | 81 / 0.235 / 0.909 / -234.28 |

### What the numbers do and do not say

* **Liquidity sweep + MSS + FVG effectively never triggered**: exactly **one**
  confirmed setup in six months across all six timeframes. The dominant rejection
  is `no_liquidity_sweep` (the level must be swept by the first candle after the
  most recent confirmed 2-left/2-right swing low, which the market usually has
  already passed). One trade is **far too small a sample** to say anything; it is
  reported, not concluded upon.
* **Fibonacci, EMA pullback and session breakout all lost money** under the
  repository's defaults on this window; profit factors are all below 1.0 and win
  rates are ~22-25% against targets that are not large enough to compensate.
* **Session breakout is the only leg with an out-of-sample-strength segment**
  (validation PF 1.52, +909), but it is negative in development and out-of-sample
  - i.e. regime-dependent inconsistency, **not** a robust edge. No superiority is
  claimed.
* The **conservative scenario** loses far less in dollars simply because it risks
  a quarter of the size; it does not turn any strategy profitable except that
  Fibonacci is roughly break-even (PF 0.998, net -$10).
* The **combined portfolio loses more than any single leg** under the primary
  scenario because the shared caps let several losing strategies trade at once
  (-22.67% with a 34.6% max drawdown). Under the conservative caps the portfolio
  loss is smaller than the sum of its parts but still negative.

### Windowing fidelity (real H1 data, 2,898 bars)

The bounded backward window was checked against the full-prefix decision on real
history: Fibonacci **100.0%** agreement (27 vs 27 signals), EMA pullback
**99.93%** agreement (6 vs 4 signals), liquidity sweep **100.0%** agreement
(0 vs 0 signals). The session strategy's window is exact by construction and is
proven equal to the full prefix in `tests/backtest/test_lab_adapters.py`.

---

## 11. Strategies that could not be tested

All four implemented strategies were tested; none is missing. Two caveats are
recorded instead of inventing a result:

* the implemented **EMA pullback is single-timeframe**, so the multi-timeframe
  variant described in `docs/ema_pullback_rules.md` was **not** tested (it does
  not exist in code);
* the **liquidity sweep + MSS + FVG** strategy was tested but produced a single
  trade, so its performance is inconclusive rather than unavailable.
