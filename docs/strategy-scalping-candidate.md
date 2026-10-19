# Risk-controlled XAUUSD scalping candidate — research record

Objective: determine **whether** an automated XAUUSD scalping strategy can
achieve a positive average daily profit after realistic costs, with **$10/day as
a soft, aspirational target** (never a guarantee). This is a read-only research
task: `trading_enabled=False`, `read_only=True`, no order-submission path.

The existing Fibonacci strategy and every previous report are preserved
(`reports/backtests/`, `reports/research/`, `reports/research_audit/`,
`reports/forward/`).

---

## 1. Requirements → how they are met

| # | Requirement | Where it lives |
| --- | --- | --- |
| 1 | Preserve Fibonacci + previous reports | No Fibonacci engine/confirmation file changed; all report dirs intact |
| 2 | Compare trend-pullback vs breakout-retest separately | `app/backtest/research/*`, run `research_audit_...647d4067` |
| 3 | Freeze rules before scoring unseen data | Frozen fingerprints in every report; no tuning against OOS |
| 4 | Validate spread/data/fills/commission/slippage/swap | `spread_audit.py` + cost scenarios (§3) |
| 5 | Net expectancy, PF, drawdown, trades, daily distribution, losing days, regimes | `daily_report.py`, `daily_report.json`, per-strategy JSON |
| 6 | No-trade conditions | `gates.py` (+ simulator rejections + forward operational rejections) |
| 7 | Stop-loss / max-position / daily-loss / exposure limits | `RiskPolicy` enforced by the research simulator |
| 8 | $10 soft objective; no forcing/martingale/sizing-up | Documented policy; no such code exists (§6) |
| 9 | Shadow workflow, hypothetical vs broker separate | `app/strategy/research_forward.py` (`source="research_forward"`) |
| 10 | Explicit approval before enabling demo submission | Not enabled; approval gate documented (§7) |

---

## 2. Verified spread/data/fill/commission/swap assumptions

Verified live (point 0.01; `symbol_info.spread` and rates `spread` are **points**;
`spread_price = points * point`, converted once). Measured this session:

| Category | Mean | Median | p95 | n |
| --- | --- | --- | --- | --- |
| **tick-level bid/ask (true)** | **46.5** | **47.0** | **59.0** | 70,983 |
| bar-level M5 (per-bar sample) | 14.3 | 13.0 | 27.0 | 5,000 |
| live snapshot | 32.0 | – | – | 1 |

* **Fills**: entry at the confirming candle close; exits at the exact stop/target
  level, or the candle close for time/trend/EOD exits; a candle spanning both the
  stop and the target is `ambiguous` (no fill guessed). Backtests presume
  stop-first unless exact-tiling M1 evidence proves target-first.
* **Commission**: no broker spec → modelled only as labelled assumption scenarios
  ($7 and $10 per lot round turn → `per_lot / contract_size`); headline excludes it.
* **Slippage**: folded into the cost-sensitivity grid (0/20/38/46/55/80 points),
  labelled assumptions.
* **Swap**: points-mode terms from the instrument (mode 1, long −12.6, short
  −4.6) applied per overnight rollover as an assumption scenario; excluded from
  headline net.
* **Data completeness**: `build_replay_dataset` rejects forming bars and flags
  incomplete coverage; bar counts and warnings are in each report.
* **Cost used for the daily figures**: the **measured per-trade spread** scenario.

---

## 3. Cost sensitivity (net of closed trades)

| Spread scenario (pts) | trend_pullback | breakout_retest | fibonacci |
| --- | --- | --- | --- |
| measured per-trade (~7.8) | +3,180 | −1,202 | −48,431 |
| assumed 20 | +318 | −1,244 | −49,218 |
| assumed 38 | −4,700 | −1,396 | −50,380 |
| **tick-measured ~46** | ≈ −6,900 | ≈ −1,460 | ≈ −50,900 |
| assumed 55 | −9,440 | −1,539 | −51,477 |

**At the tick-measured spread (~46–47 pts) the trend strategy is negative.** Its
marginal positive full-window result exists only under an unrealistically low
cost.

---

## 4. Daily P&L distribution, losing days and regimes (run `...647d4067`)

Account basis: 100,000 equity, 0.5% risk/trade (simulator units; the $10 target is
compared in these units — see the scale caveat below). Grouped by trade exit day
(UTC), measured per-trade spread, end-of-data marks excluded.

| Strategy | Trading days | Mean/day | **Median/day** | Min | Max | Win days | **Losing days** | **Losing-day rate** | Days ≥ $10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| trend_pullback | 95 | +33.5 | **−553** | −3,893 | +8,169 | 38 | **57** | **0.60** | 38 |
| breakout_retest | 5 | −240 | −394 | −912 | +581 | 2 | 3 | 0.60 | 2 |
| fibonacci | 70 | −692 | −469 | −2,209 | −234 | 0 | **70** | **1.00** | 0 |

Volatility regimes (ATR(14) terciles on M5, net P&L):

| Regime | trend_pullback | breakout_retest | fibonacci |
| --- | --- | --- | --- |
| low volatility | −10,233 (PF 0.79) | −699 (PF 0.58) | −15,416 (0 wins) |
| mid volatility | +176 (PF 1.00) | −503 | −16,654 |
| **high volatility** | **+13,237 (PF 1.26)** | – | −16,361 |

Monthly net (trend): Apr +628, May −3,053, **Jun +18,812**, **Jul −11,282**,
Aug −2,107, Sep +11,782, **Oct −11,600** — highly unstable.

**Reading.** The mean day is positive only because of a handful of large winning
days; the **median day is a heavy loss** and **60% of days lose**. The trend edge
lives almost entirely in **high-volatility** regimes and a few months; it loses
badly in low-volatility regimes. That is not the profile of a positive
average-daily-profit scalper.

**Scale caveat.** These are simulator P&L units at 100k equity / 0.5% risk. A
literal "$10/day" would require scaling position size by roughly 1/50; that
scales every number down uniformly and leaves the **negative median and 60%
losing-day rate** unchanged, so the target is not supported.

Expectancy / profit factor / drawdown / trade count (from the same run): Fibonacci
115 trades / PF 0.00 / DD 48.4%; trend 428 trades / PF 1.026 / DD 26.0%;
breakout 9 trades / PF 0.47 / DD 1.2%.

---

## 5. No-trade conditions implemented

`app/backtest/research/gates.py` defines the canonical, tested policy
(`evaluate_entry_gates`) with four categories:

* **data** — missing / insufficient / non-monotonic / stale candles, unknown time;
* **spread** — spread unavailable or above the maximum;
* **metadata** — symbol point, contract size or broker stop level missing/invalid;
* **risk** — max open positions, daily loss, aggregate exposure, stop-distance
  bounds, unknown stop distance.

Enforcement in this task:
* the research simulator enforces spread, stop-distance, open-position,
  daily-capacity and symbol/timeframe limits and reports `rejections_by_reason`;
* the forward validator enforces the data/spread/metadata conditions and reports
  operational rejections (`missing_timeframe_data`, `candle_read_failed`,
  `duplicate`, `over_cap`);
* a failed gate only **blocks** — it can never force or enlarge an entry.

Risk limits respected: `RiskPolicy` max-open-positions, max-daily-loss,
max-daily-drawdown, max-aggregate-risk, per-trade and max-per-trade risk, and
min/max stop distance — all applied by the simulator's sizing/gating.

---

## 6. Soft objective and anti-martingale policy

* The `$10/day` figure is `research_daily_profit_target` (default 10). It is used
  **only** to count historical days that reached it. It is never enforced, never
  forces an entry and never changes size.
* Position size is fixed-fractional: `budget = min(equity·risk%, equity·max_risk%)`
  capped by aggregate/daily remaining, divided by the stop distance. **There is no
  size increase after a loss, no martingale, no grid, no recovery doubling, and no
  guarantee of daily profitability.** (Grep-verified: no such logic exists.)

---

## 7. Shadow workflow and the approval gate

* `app/strategy/research_forward.py` runs the **frozen** rules over incoming
  completed live candles and records hypothetical observations with
  `source="research_forward"` in the read-only shadow store, de-duplicated by
  deterministic id across reconnects/restarts. Outcomes advance on completed
  candles only; ambiguous candles are recorded as such.
* Hypothetical research results are **separate** from broker trades (a different
  table) and from live Fibonacci shadow observations (`source="live_strategy"`).
  Reports are at `reports/forward/` and read-only API
  `/api/strategy/forward/{status,observations,report}`.
* **Approval gate**: demo order submission is **not enabled**. `execution_enabled`
  defaults to `False`, `app_read_only=True`, and execution authorization starts
  disarmed. Any future change that would enable demo order submission requires
  **explicit human approval** (and the existing demo-account verification) — this
  task grants none and adds no order path. Live trading remains unsupported.

---

## 8. Files changed

New: `app/backtest/research/daily_report.py`, `app/backtest/research/gates.py`,
`tests/backtest/test_daily_and_gates.py`, `docs/strategy-scalping-candidate.md`,
and generated report artifacts.

Modified: `app/backtest/research/runner.py` (daily/regime + no-trade-policy
sections and new outputs), `app/config.py` (`research_daily_profit_target`).

Reused unchanged: the frozen strategies, `RiskPolicy`, the `run_research_mt5`
pipeline, the forward validator, all previous reports.

New outputs in the run directory: `daily_report.json`, `daily_pnl.csv`
(plus the existing per-strategy JSON and `cost_scenarios.*`).

---

## 9. Test results

* Backend: **969 passed, 23 deselected** (`pytest -m "not live"`), including **22
  new deterministic tests** for the daily distribution, losing-day frequency,
  ATR regimes, `$`-target counting, every no-trade gate category, and safety
  (execution disabled / no order functions in the new modules). The phase-boundary
  guard passes.
* Frontend (unaffected): **268 passed**; TypeScript typecheck **exit 0**;
  production build **exit 0**.
* Real read-only runs completed; no environmental failures.

---

## 10. Conclusion — is there sufficient evidence for a controlled demo trial?

**No.** Based on the actual numbers above:

* **Fibonacci** — structurally unprofitable (0 winning days out of 70; PF 0.00).
  Not a candidate.
* **Trend-following pullback** — positive *mean* full-window only under an
  unrealistically low cost; **negative at the tick-measured spread (~46–47 pts)**;
  **median day is a large loss** and **60% of days lose**; the apparent edge is
  concentrated in high-volatility regimes and a couple of months. It does **not**
  satisfy a positive average-daily-profit objective.
* **Breakout-retest** — **9** historical trades and **5** forward trading days;
  far too few to evaluate.

Recommendation: **do not proceed to a controlled demo trial.** Continue the
read-only forward observation (already running) to accumulate a genuine
out-of-sample record across more regimes and with the tick-measured cost floor,
and revisit only if a materially larger sample shows a positive **median** day
with an acceptable losing-day rate. No winner is selected on in-sample returns.
