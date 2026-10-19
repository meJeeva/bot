# XAUUSD cost-model and strategy-robustness audit

Read-only validation of the research framework. **No strategy rule, risk limit
or execution path was changed.** New run-specific outputs were written to
`reports/research_audit/`; the earlier `reports/research/` runs are preserved.

* Audit run: `research_audit_xauusd_20260414_20261014_9136b8f7`
* Window (UTC): `2026-04-14` → `2026-10-14` (same verified interval as the
  existing Fibonacci reports). Symbol `XAUUSD`; decision TF `M5`; context
  `M15`,`H1`; intrabar evidence `M1`.
* Cost model version `2` (the version is part of the run id, so a new cost
  convention never overwrites an older report directory).
* Reproduce:
  `cd backend && python -m app.backtest.research.cli --start 2026-04-14 --end 2026-10-14 --timeframes M1,M5,M15,H1`

> **Headline.** The trend-following pullback's small positive edge is an artifact
> of an unrealistically low spread assumption. At the live-realistic spread
> (≈34–55 points) it is **negative**. The Fibonacci baseline is structurally
> unprofitable on this window, and the breakout-retest sample is **9 trades**.
> **The evidence does not support recommending any of the three for deployment.**

---

## 1. Verified spread units and conversion formula

Ground truth read from the live demo terminal (`symbol_info`, `symbol_info_tick`,
`copy_rates_from_pos`):

| Field | Value | Interpretation |
| --- | --- | --- |
| `symbol_info.point` | `0.01` | 1 point = 0.01 price |
| `symbol_info.digits` | `2` | |
| `symbol_info.spread` | `41` | **points** |
| live `symbol_info_tick` | bid 4144.51 / ask 4144.92 | spread = 0.41 price = **41 points** |
| rates `spread` field | e.g. 13, 17, 8, 22 | **points** (integer) |

`0.41 / 0.01 = 41`, so **both** `symbol_info.spread` and the MetaTrader rates
`spread` field are in **points**.

**Conversion (applied exactly once):**

```
spread_price = spread_points * point          # 41 * 0.01 = 0.41
```

**Cost formula** (one full spread width per round trip; entry and exit bar
spreads are **averaged**, never summed):

```
spread_cost     = spread_price * volume
volume          = lots * contract_size        (default_calc_profit = volume * price_move)
commission_cost = (commission_per_lot / contract_size) * volume
swap_cost       = (|swap_points| * point * nights) * volume
net             = gross - spread_cost - commission_cost - swap_cost
```

Findings on the specific checks:

* **Unit** — points (verified above).
* **Point size source** — previously **hard-coded** `0.01`; now read from
  `symbol_info.point` (`point_source = "symbol metadata (symbol_info.point)"`).
  For XAUUSD the value is identical, but the sourcing is now correct if a broker
  used a different point.
* **Converted exactly once** — yes; `points_to_price` performs a single
  multiplication and returns `None` (never 0) on missing inputs.
* **Pairing with entry/exit times** — each trade records the spread of its own
  entry and exit bars; the applied per-trade width is `mean(entry, exit)`.
* **Double-counting / omission** — one full spread width is charged once
  (enter at ask, exit at bid). A **defect was found and fixed in this audit**:
  the per-trade scenario silently charged **zero** spread to the Fibonacci
  baseline (its evaluator records no per-bar spread). It now falls back to the
  measured mean and those trades are counted as `trades_with_assumed_spread`.
* **Live snapshots vs historical** — the live spread snapshot (`symbol_info_tick`
  at run time, a **snapshot**) is stored under
  `symbol_instrument_metadata.live_spread_snapshot` and reported separately from
  the historical per-bar distributions; it is never treated as a historical
  measurement.

---

## 2. Historical spread distributions (measured per-bar, points)

From `spread_distribution.json` (count, median, mean, upper percentiles):

| TF | bars | mean | median | p90 | p95 | p99 | max | zero-spread bars |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| M1 | 100,256 | 16.04 | 15 | 27 | 32 | 46 | 205 | 7,548 |
| **M5** | 34,569 | **7.80** | 8 | 16 | 19 | 30 | 281 | 4,366 |
| M15 | 11,524 | 6.41 | 7 | 11 | 13 | 21 | 281 | 1,466 |
| H1 | 2,882 | 5.67 | 7 | 8 | 9 | 13 | 58 | 367 |

Per-month M5 distributions are in `spread_distribution.json` (`by_month`).

**Data-quality caveats (important):**

* The MT5 per-bar `spread` field is a **bar-level sample** (likely at/near bar
  open or the bar minimum), **not** a tick-level average. Its mean **falls as the
  timeframe rises** (M1 16.0 → M5 7.8 → M15 6.4 → H1 5.7), which is internally
  inconsistent as a single "spread" concept, so it cannot be read as the true
  average cost a trade would actually pay.
* 10–13 % of M5/M15 bars carry a `0` spread, further indicating the field is
  unreliable in places.
* **The measured historical mean (7.8 pts) is far below the live snapshot (34 pts)
  and the earlier live observations (~38–55 pts).** The historical per-bar field
  therefore **understates realistic live execution cost**; it is a floor, not a
  central estimate.

---

## 3. Cost sensitivity (all three strategies, `cost_scenarios.csv`)

Net P&L of **closed** trades (end-of-data marks excluded), USD, on a 100,000
account. `measured_*` scenarios are **measured**; `fixed_*`/commission/swap are
labelled **assumptions**.

| Scenario | points | trend_pullback net | PF | fibonacci net | breakout_retest net |
| --- | --- | --- | --- | --- | --- |
| measured per-trade (entry/exit bars) | ~7.8 | **+3,180** | 1.022 | −48,431 | −1,202 |
| measured mean | 7.80 | +3,721 | 1.026 | −48,431 | −1,141 |
| measured median | 8 | +3,664 | 1.025 | −48,444 | −1,143 |
| measured p90 | 16 | +1,434 | 1.010 | −48,960 | −1,210 |
| measured p95 | 19 | +597 | 1.004 | −49,154 | −1,235 |
| measured p99 | 30 | −2,470 | 0.983 | −49,864 | −1,328 |
| assumed 20 pts | 20 | +318 | 1.002 | −49,218 | −1,244 |
| assumed 38 pts | 38 | **−4,700** | 0.969 | −50,380 | −1,396 |
| assumed 46 pts | 46 | **−6,931** | 0.954 | −50,896 | −1,463 |
| assumed 55 pts | 55 | **−9,440** | 0.938 | −51,477 | −1,539 |
| assumed 80 pts | 80 | −16,411 | 0.896 | −53,090 | −1,750 |
| measured + $7/lot comm | ~7.8 | +1,229 | 1.008 | −48,379 | −1,261 |
| measured + $10/lot comm | ~7.8 | +392 | 1.003 | −48,573 | −1,286 |
| measured + swap (assumed nights) | ~7.8 | +2,940 | 1.020 | −48,780 | −1,202 |

The scenario table reports gross P&L, spread cost, commission, swap and net
**separately** (`gross_pnl_all_trades`, `spread_cost_total`,
`commission_cost_total`, `swap_cost_total`, `total_cost`, `net_pnl_closed`,
`net_pnl_all_trades`, plus `end_of_data_mark_pnl`).
The older single "central cost" grid is still written for continuity, but the
**audit headline is `measured_per_trade`**.

---

## 4. Commission and swap assumptions and limitations

* **Commission** — no broker specification is available, so it is modelled only
  as labelled **assumption** scenarios (0 default; $7 and $10 per lot round turn)
  converted as `commission_price = per_lot / contract_size`
  (`contract_size = 100`). The headline net excludes commission. $7/lot ≈ 0.07
  price units.
* **Swap** — modelled from the instrument's **points-mode** terms read at run
  time (`swap_mode=1`, `swap_long=-12.6`, `swap_short=-4.6`), applied per
  overnight rollover as `|swap_points| * point * nights`, with nights counted on
  UTC day boundaries (a broker 3×-swap weekday is honoured only if
  `swap_rollover3days` is available). This is an **assumption about the rollover
  schedule**; it is a separate scenario and is **not** in the headline net. It is
  small here (≈240 total for the trend leg) because trend positions rarely hold
  overnight in this sample.
* Both are written as `is_assumption=true`. Current costs are **not** applied to
  historical periods as if measured then; the historical figure is the measured
  per-bar spread, and every other scenario says "assumed".

---

## 5. Updated chronological performance and risk

Trend-following pullback (frozen rules), central-cost basis
(`trend_pullback_breakdown.json`):

| Slice | Trades | Net P&L | PF | Max DD % |
| --- | --- | --- | --- | --- |
| development (Apr 14–Jul 14) | 206 | +13,386 | 1.205 | 7.8 |
| validation (Jul 14–Aug 20) | 86 | **−20,078** | 0.440 | 20.1 |
| out-of-sample (Aug 20–Oct 14) | 136 | +10,412 | 1.240 | 14.5 |
| full | 428 | +3,721 | 1.026 | 26.0 |

| Direction | Trades | Net P&L | PF |
| --- | --- | --- | --- |
| buy | 99 | **−6,470** | 0.819 |
| sell | 329 | +10,191 | 1.094 |

| Month | Trade count | Net P&L |
| --- | --- | --- |
| 2026-04 | 16 | +592 |
| 2026-05 | 72 | −3,026 |
| 2026-06 | 97 | +18,535 |
| 2026-07 | 68 | **−11,166** |
| 2026-08 | 70 | −1,953 |
| 2026-09 | 64 | +11,981 |
| 2026-10 | 41 | **−11,241** |

Exit mix: stop_loss 279 trades net −144,506; take_profit 148 trades net +148,226.

**Concentration:** the best 5 trades contribute **+5,755**, which is **181 %** of
the full-window net (+3,180); only 34.7 % of closed trades are positive. The
headline therefore depends on a handful of winners.

Fibonacci baseline (unchanged): 115 trades, 111 closed, **all 111 are
stop-losses** (the default policy attaches no take-profit) → win rate 0, PF 0,
realized net ≈ −48,431. The `net_pnl_all_trades` figure (+29,688) is dominated by
a **+78,133 floating end-of-data mark** on 4 open positions — a mark, not a
realized result, and reported separately.

Breakout-retest: 9 trades, PF 0.45, negative under every scenario — **no
conclusion is possible from 9 trades.**

Portfolio-level results (above) are reported separately from the common-entry
diagnostic, which remains in `cost_scenarios.json` / `*_trades.csv`; no signals
were combined across strategies.

---

## 6. Why the trend strategy lost in validation

The validation window is `2026-07-14 → 2026-08-20`. Its −20,078 loss is not a
cost artifact — it is a **market-regime** effect: the monthly breakdown shows
July at −11,166 (the worst month, PF 0.59) with August adding −1,953, i.e. the
strategy was whipsawed by stops during that stretch (279 of 428 exits are stops).
It coincided with a drawdown that reached ~20 % inside the window. Because the
edge is (a) concentrated in ~5 trades, (b) almost entirely **sell-side**
(buys net −6,470), and (c) sensitive to cost, the strategy is regime-dependent
rather than robust. No parameter was re-tuned against the validation or
out-of-sample window to change this.

---

## 7. Actual test results

* Backend: **921 passed, 23 deselected** (`pytest -m "not live"`), including
  **+20 new deterministic cost tests** (`tests/backtest/test_research_costs.py`)
  for unit conversion, spread distributions, missing-metadata fallback, one-width
  (no double-count), volume scaling, commission/swap conventions, EOD separation
  and reproducibility, plus the existing phase-boundary guard.
* Frontend (unaffected): **268 passed**; TypeScript typecheck **exit 0**;
  production build **exit 0**.
* Live read-only audit run completed and wrote `reports/research_audit/…9136b8f7/`.
* No environmental failures.

---

## 8. Honest conclusion

The current evidence does **not** support further demo testing as a path to
deployment for any of the three, because:

1. **Fibonacci baseline** — structurally unprofitable on this window (all exits
   are stops; no take-profit). Realized net ≈ −48k.
2. **Trend-following pullback** — positive only under an unrealistically low
   spread (≤ ~20 pts). At the live-realistic spread (≈34–55 pts) it is
   **negative** (−4.7k to −9.4k), its edge is sell-side only, concentrated in ~5
   trades, and it suffered a −20k validation-period loss. This is not a robust
   edge.
3. **Breakout-retest** — 9 trades; **insufficient** to establish anything.

If any further work is pursued, it should remain **paper/demo only** and would
require: a realistic cost floor of at least 46–55 points (not the historical
per-bar field), a materially larger sample across multiple regimes, commission
and swap confirmed against an actual broker schedule, and an explicit
investigation of the sell-side dependence — before any deployment discussion.
**Nothing in this audit changes the strategies or enables execution;
`trading_enabled=False`, `read_only=True`, no order path.**
