# Read-only forward validation of XAUUSD strategies

Implemented the minimum capability to validate the frozen **trend-following
pullback** and **breakout-retest** rules against incoming live XAUUSD data
without submitting orders. Read-only throughout; the Fibonacci engine, its
confirmation rules and the execution path are unchanged.

---

## 1. Verified spread-data findings

### Units (verified against the live terminal)

| Source | Value | Unit |
| --- | --- | --- |
| `symbol_info.point` | `0.01` | 1 point = 0.01 price |
| `symbol_info.spread` | e.g. `41` | **points** |
| live `symbol_info_tick` | bid 4144.51 / ask 4144.92 = 0.41 price | 0.41 / 0.01 = **41 points** |
| rates `spread` field | e.g. 13, 17, 8, 22 | **points** (integer) |

Conversion, applied **exactly once**: `spread_price = spread_points * point`.

### The bar-level field materially understates the true spread (quantified)

Measured live this run (M5 bar window = last 5,000 bars; tick window = last 6 h,
70,983 ticks with both bid and ask):

| Category | Mean (pts) | Median | p95 | n | What it is |
| --- | --- | --- | --- | --- | --- |
| **tick-level historical** (bid/ask) | **46.5** | **47.0** | **59.0** | 70,983 | Genuine observed spread, the only true series |
| bar-level historical M1 | 22.2 | 21.0 | 40.0 | 5,000 | per-bar sample |
| bar-level historical M5 | 14.3 | 13.0 | 27.0 | 5,000 | per-bar sample |
| bar-level historical M15 | 9.6 | 8.0 | 17.0 | 5,000 | per-bar sample |
| bar-level historical H1 | 5.2 | 4.0 | 8.0 | 5,000 | per-bar sample |
| live snapshot | 32.0 | - | - | 1 | `symbol_info_tick` at run time |

**Conclusion.** The tick-level bid/ask mean (46.5 pts) is ≈ **3×** the M5
bar-level field (14.3) and ≈ **9×** the H1 field (5.2). The bar-level `spread`
field **decreases monotonically with timeframe** and is nowhere near the observed
bid/ask spread, so it cannot be used as a historical cost proxy. This reconciles
the earlier audit: the six-month M5 bar mean was 7.8 pts while live observations
are 38–55 pts, and the tick-level measurement here (mean 46.5, median 47, p95 59)
matches those live observations, not the bar field.

Four categories are kept strictly separate in the audit output
(`reports/forward/spread_audit.json` → `categories`):

* **bar-level historical** - MT5 rates `spread`, a bar-level sample (points);
* **tick-level historical** - bid/ask from `copy_ticks_range`, the true series
  (points), available only for the retained tick window;
* **live snapshot** - `symbol_info_tick` at run time, labelled `SNAPSHOT`, *not*
  a historical average;
* **assumed stress** - fixed 20/38/46/55/80-point scenarios, labelled
  assumptions.

A live snapshot is never described as a historical average.

---

## 2. What was built

### Forward validator (`app/strategy/research_forward.py`)

`ResearchForwardService` runs the **unchanged** frozen rules and records
*hypothetical* observations:

* consumes new **completed** candles through the existing market-data pipeline
  (`MarketMonitor.get_candles`); forming bars are ignored;
* builds the same no-look-ahead `MarketView` the historical audit used, from the
  strategies' own EMA `periods`;
* evaluates only decision candles newer than an in-memory watermark (last
  `research_forward_scan_bars`), so there is no future information;
* **stable ids**: `setup_id = "{strategy}:{timeframe}:{candle_time}"` and the
  store's `UNIQUE(setup_id, scenario)` make repeated scans, reconnects and
  restarts no-ops;
* records an observation only when the frozen rule produced entry/stop/target;
  missing target or a missing quote is recorded as a `data_note`;
* advances outcomes with the same completed-candle semantics as the live
  shadow validator (shared `advance_observation`); a candle spanning both the
  stop and the target is `ambiguous` (no fill guessed);
* writes observations through the existing read-only shadow-observation store
  with `source="research_forward"`, kept separate from the live Fibonacci shadow
  (`source="live_strategy"`) and from broker trades;
* samples the live spread at signal time as a **snapshot** and charges only a
  documented **cost assumption**;
* excludes itself from any order/execution surface (asserted by tests).

It runs in the backend lifespan alongside the Fibonacci shadow validator and is
exposed read-only at `/api/strategy/forward/{status,observations,report}`.

### Spread audit (`app/backtest/research/spread_audit.py`)

Pure, testable helpers (`summarize_values`, `tick_spreads`,
`build_spread_audit`) plus `audit_mt5_spreads(...)` which reads genuine bar and
tick data (read-only) and writes the four-category audit.

### Exact files changed

**New**
* `backend/app/strategy/research_forward.py`
* `backend/app/backtest/research/spread_audit.py`
* `backend/tests/backtest/test_research_forward.py`
* `backend/tests/backtest/test_spread_audit.py`
* `docs/strategy-forward-validation.md` (this file)
* `reports/forward/` (generated: `forward_report.json`, `spread_audit.json`)

**Modified**
* `backend/app/storage.py` - optional `source` scoping on the shadow queries.
* `backend/app/strategy/shadow.py` - extracted shared `advance_observation`;
  scoped the live shadow to `source="live_strategy"`.
* `backend/app/config.py` - `research_forward_*` settings.
* `backend/app/main.py` - start/stop wiring + endpoint registry.
* `backend/app/api/deps.py` - `get_research_forward`.
* `backend/app/api/strategy.py` - three read-only forward endpoints.
* `backend/app/schemas/strategy.py` - forward observation/status/report schemas.
* `backend/app/backtest/research/strategies.py` - per-rule EMA `periods`.
* `backend/app/backtest/research/runner.py` - use the rule's own `periods`.

No file under `app/execution/`, and no Fibonacci engine/confirmation file, was
changed. Existing backtest reports (`reports/backtests/`, `reports/research/`,
`reports/research_audit/`) are preserved.

---

## 3. Forward-observation report locations

* Rolling report: `reports/forward/forward_xauusd_20261014_ae34914b/forward_report.json`
* Spread audit: `reports/forward/spread_audit.json`
* Observation store: `reports/forward/forward.db` (SQLite, `source="research_forward"`)

Live API (read-only): `GET /api/strategy/forward/status`,
`GET /api/strategy/forward/observations`, `GET /api/strategy/forward/report`.

The report file is a **mutable rolling snapshot** (unlike immutable backtest
runs); it is rewritten each pass under a run id keyed by the symbol, the
strategy fingerprints and the day.

---

## 4. Cost assumptions

* The **headline** net in the forward report is gross points minus a
  `research_forward_cost_points` assumption (default 0), reported separately.
* The report carries an explicit **cost-sensitivity grid** at 0/20/38/46/55/80
  points, each labelled `is_assumption` except 0.
* The sampled spread is stored per observation as a **snapshot**, never applied
  as if it were a historical average and never substituted for a measured cost.
* Recommended realism floor, from §1: the tick-level median/mean (~46–47 pts).

---

## 5. Forward results (demonstration run)

This run used a **500-bar warm start** (the service evaluated the most recent
500 completed M5 bars in one pass; its steady-state default is 5-bar scans every
30 s). This is recent-window evaluation, not long-horizon observation — it is
labelled as such and must not be read as out-of-sample validation.

Window: the most recent M5 history at run time (2026-10-14), XAUUSD, decision
TF M5.

| Strategy | Entries | Resolved | Open | Ambiguous | Net (pts, cost 0) | PF | Expectancy (pts) | Max DD (pts) | Open risk (pts) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| trend_pullback | 24 | 23 | 1 | 0 | **−76.4** | 0.32 | −3.32 | 99.6 | 758 |
| breakout_retest | 0 | 0 | 0 | 0 | 0.0 | - | - | - | 0 |

Trend-pullback net by cost assumption (points): 0 → −76.4; 20 → −536.4;
38 → −950.4; 46 → −1134.4; 55 → −1341.4; 80 → −1916.4. It is negative **before
any cost** and catastrophically negative at the tick-measured spread.
Breakout-retest produced **no** signals in the recent window (its frozen filter
is very restrictive; 9 trades in six months historically).

The 24 trend observations all sampled the same snapshot (41 pts) because they
were recorded in a single pass; a continuously running service samples a
different snapshot per signal.

---

## 6. Test results

* Backend: **949 passed, 23 deselected** (`pytest -m "not live"`), including the
  phase-boundary guard and **28 new tests**:
  * `test_research_forward.py` (16): records from frozen rules; repeated scan and
    restart de-duplication; target/stop/ambiguous/still-open advancement;
    forming-candle handling; snapshot-vs-historical labelling; metrics withheld
    below 20 resolved observations and provided above; cost-sensitivity; report
    file; no order/execution surface; read-only API endpoints.
  * `test_spread_audit.py` (12): point conversion once, tick spread from bid/ask
    (skips last-only/negative), percentile summaries, four-category labels,
    snapshot not described as historical, once-only price→points derivation,
    understatement warning, assumption labelling.
* Frontend (unaffected): **268 passed**; TypeScript typecheck **exit 0**;
  production build **exit 0**.
* Live read-only runs completed; no environmental failures.

---

## 7. Honest conclusion

**The current evidence does not support recommending either strategy for
deployment, and does not yet justify further demo testing as a path to
deployment.** Specifically:

1. The forward trend-pullback sample is negative (−76 pts, PF 0.32) over the
   recent window **before any cost**, and far more negative at the realistic
   tick-measured spread (~46–47 pts). This is consistent with the historical
   audit (positive only under an unrealistically low cost, otherwise negative).
2. The breakout-retest rule produced **no** signals forward and only 9 trades
   historically — far too few to evaluate.
3. The spread evidence is now unambiguous: the true bid/ask spread (median
   47 pts) is about 3× the M5 bar-level field, so any result computed with the
   bar-level field is optimistic.

The forward validator is now in place and will accumulate a genuine
out-of-sample record. A meaningful conclusion requires a materially larger
forward sample across multiple regimes, with realistic costs. Until then, no
profitability claim is made and **no deployment is recommended**.

Safety: `trading_enabled=False`, `read_only=True`, no order-submission path,
execution authorization/verification unchanged, no strategy rule modified.
