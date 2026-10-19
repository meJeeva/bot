# Strategy research results (one run)

> **Prominent disclosure.** These are **hypothetical simulation** results from a
> single `XAUUSD` window and a single market regime. They are **not** broker
> fills, **not** live Fibonacci signals and **not** shadow-validation outcomes.
> Commission and swap are **unknown and not modelled**; cost is the measured
> per-bar spread plus a labelled assumption grid. **No strategy is declared
> superior**: the numbers below must not be read as a profitability claim.

* Run id: `research_xauusd_20260414_20261014_30e0af1e`
* Window (UTC): `2026-04-14` → `2026-10-14` (same window as the existing
  Fibonacci reports, so the legs share one verified interval).
* Symbol: `XAUUSD`. Decision timeframe: `M5`. Context: `M15`, `H1`. Intrabar
  evidence: `M1`.
* Cost basis: **measured mean per-bar spread** = `0.07795` price units
  (≈ 7.8 points) over 34,563 M5 bars; applied identically to every leg.
* Chronological split (by entry time): development 0–50%, validation 50–70%,
  out-of-sample 70–100%. Rule constants were frozen in code before scoring.
* Reports: `reports/research/research_xauusd_20260414_20261014_30e0af1e/`
  (`fibonacci.json`, `trend_pullback.json`, `breakout_retest.json`,
  `comparison_summary.json`/`.csv`, per-strategy `*_trades.csv`, `README.md`).

## Side-by-side (net of the central cost)

| Strategy | Window | Trades | Closed | Win rate | Profit factor | Expectancy | Net P&L | Max DD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Fibonacci (stop-only baseline) | full | 115 | 111 | 0.000 | 0.00 | -436.31 | -48,430.42 | 48.4% |
| Fibonacci | development | 83 | 82 | 0.000 | 0.00 | -444.79 | -36,472.69 | 36.5% |
| Fibonacci | validation | 10 | 10 | 0.000 | 0.00 | -447.47 | -4,474.66 | 4.5% |
| Fibonacci | out-of-sample | 22 | 19 | 0.000 | 0.00 | -393.85 | -7,483.08 | 7.5% |
| Trend pullback | full | 428 | 427 | 0.347 | 1.03 | +8.71 | +3,721.25 | 26.0% |
| Trend pullback | development | 206 | 206 | 0.388 | 1.21 | +64.98 | +13,386.36 | 7.8% |
| Trend pullback | validation | 86 | 86 | 0.186 | 0.44 | -233.46 | -20,077.66 | 20.1% |
| Trend pullback | out-of-sample | 136 | 135 | 0.385 | 1.24 | +77.13 | +10,412.55 | 14.5% |
| Breakout-retest | full | 9 | 9 | 0.222 | 0.47 | -126.76 | -1,140.84 | 1.2% |
| Breakout-retest | development | 3 | 3 | 0.000 | 0.00 | -292.13 | -876.39 | 0.9% |
| Breakout-retest | validation | 4 | 4 | 0.250 | 0.54 | -88.05 | -352.18 | 0.8% |
| Breakout-retest | out-of-sample | 2 | 2 | 0.500 | 1.18 | +43.86 | +87.72 | 0.5% |

## What the numbers do and do not say

* **Fibonacci baseline.** All 111 closed trades exited at the stop (the default
  policy attaches no take-profit), leaving 0 wins on this window. This agrees
  with the earlier on-disk Fibonacci comparison, which also found the stop-only
  behaviour unprofitable over this period.
* **Trend pullback.** A marginal full-window edge (profit factor ≈ 1.03) that is
  **regime dependent**: strongly positive in development and out-of-sample but
  clearly negative in validation. That inconsistency is the opposite of a robust
  conclusion and is exactly why no superiority is claimed.
* **Breakout-retest.** Only **9 trades** in six months — the no-chase + retest
  filter is very restrictive. **Nine trades is far too few to say anything**;
  the result is inconclusive by construction.
* **Cost sensitivity** and **exit mix** per strategy are in each
  `*.json` (`cost_sensitivity`, `exit_counts`, `rejections_by_reason`).

## Missing data and assumptions (repeated for emphasis)

* No tick-level or full-window M1 spread series: cost is the per-bar spread plus
  an assumption grid; **commission and swap are omitted**.
* One symbol, one six-month regime: results do not generalise.
* Research legs are multi-timeframe simulations; the Fibonacci baseline is
  per-timeframe, so the comparison is **directional, not an exact match**.
* Higher-timeframe rules use completed bars only, which removes (never adds)
  signals relative to a forward-looking rule.
* All research trades are labelled `source="research_simulation"` and are kept
  distinct from replay, shadow validation and real broker orders.

## Reproduce

```
cd backend
python -m app.backtest.research.cli --start 2026-04-14 --end 2026-10-14 \
    --timeframes M1,M5,M15,H1 --output-dir ../reports/research
```

Read-only: `APP_READ_ONLY=True`, `trading_enabled=False`, no order path.
