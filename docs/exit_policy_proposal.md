# Exit Policy Audit and Proposal — Fibonacci MT5 Bot

Status: **audit only.** No code, configuration, strategy parameter, live behaviour,
or existing report was changed. `trading_enabled=False`, `read_only=True`, and the
direction-mapping and duplicate-entry fixes are untouched. No MT5 order was placed.

Scope audited: `backend/app/backtest/evaluator.py`, `backend/app/backtest/runner.py`,
`backend/app/execution/risk.py`, `backend/app/strategy/{engine,setup,fibonacci,confirmation}.py`,
`backend/app/config.py`, the backtest tests, and the six-month report at
`reports/backtests/xauusd_20260414_20261014_4eea7638/`.

---

## 1. Current exit contract

### 1.1 Entry (implemented)

- A trade is simulated **only** on the exact candle where a setup transitions to
  `CONFIRMED_BUY` / `CONFIRMED_SELL`. `BacktestEngine._should_enter_now`
  (`evaluator.py:642`) matches the confirmation transition's `candle_time` to the
  candle currently being simulated, so each confirmed setup produces **at most one**
  entry. This is the duplicate-entry fix and it is preserved.
- Entry price = the confirming candle's **close**
  (`_simulate_entry`, `evaluator.py:670`). Slippage is zero by assumption.
- Direction is mapped explicitly at the integration boundary via
  `map_setup_direction_to_execution` (`evaluator.py:76`): `bullish -> buy`,
  `bearish -> sell`; unknown values raise `BacktestConfigError` (never coerced).
  The original strategy vocabulary is retained in `BacktestTrade.setup_direction`.
- Every candidate is passed through the real `RiskEngine.assess`. If rejected, the
  signal is recorded with `executed: False` and machine-readable `rejection_reasons`;
  no trade is opened.

### 1.2 Stop loss (implemented)

- Stop = the setup's **structural invalidation boundary**
  (`FibonacciSetup.get_invalidation_boundary`, `setup.py:255`): for a bullish setup
  `swing_low - structural_buffer`; for a bearish setup `swing_high + structural_buffer`.
  Buffer defaults to 0 points (`strategy_structural_buffer_points=0`).
- The exit loop tests the candle's full range: buy stops when `candle.low <= stop`,
  sell stops when `candle.high >= stop` (`_check_position_exit`, `evaluator.py:872`).
- Exit price is recorded as the stop level **exactly** (no gap/slippage).
- The risk engine additionally enforces `min/max_stop_distance_points` (100–5000) at
  entry time, so an over-wide structural stop can reject the entry.

### 1.3 Take profit (implemented branch, inert under current config)

- `RiskEngine.take_profit_for` (`risk.py:652`) returns **`None` unless**
  `policy.tp_policy == "fixed_rr"` (`risk.py:656`). Current config is
  `execution_tp_policy="none"` (`config.py:218`), so `assessment.take_profit` is always
  `None`, `BacktestTrade.take_profit` is always `None`, and the
  `TradeExitReason.TAKE_PROFIT` branch (`evaluator.py:868`) **never fires**.
- The `fixed_rr` branch *is* implemented: `tp = entry ± |entry - stop| * fixed_rr`,
  rounded to symbol digits (`risk.py:658`). `execution_fixed_rr` defaults to 2.0.
- Consequence for reporting: `rr_ratio` is `None` for every trade
  (`evaluator.py:186`) and `metrics.avg_rr_ratio` is `null`.

### 1.4 Setup invalidation / expiry as an exit (enum exists; unreachable after entry)

- `TradeExitReason.SETUP_INVALIDATED` and `SETUP_EXPIRED` exist and the evaluator has
  branches for them (`evaluator.py:877`).
- However, entry happens only at confirmation, and `CONFIRMED_BUY`/`CONFIRMED_SELL`
  are **terminal** (`setup.py:267`, `VALID_TRANSITIONS`). `_advance_setup`
  (`engine.py:562`) is only reached for non-terminal states, so a confirmed setup is
  never advanced again and never becomes `INVALIDATED`/`EXPIRED`. The evaluator closes
  against the *frozen confirmed* setup object in `pos["setup"]`, so those two branches
  cannot trigger for an open trade.
- Pre-confirmation structural invalidation and `max_candles` expiry **do** work
  (`engine.py:568`–`597`) and correctly prevent new entries; they are just not exits.
- Net: for an **open** trade there is effectively no invalidation-based or expiry-based
  exit in the current design.

### 1.5 Opposing signals (does not exist)

- There is no reversal/opposing-signal close. A new impulse pair merely supersedes the
  timeframe's setup slot (`engine.py:413`); open positions live in
  `BacktestEngine._open_positions` keyed by `setup_id` and are unaffected. A reversal
  opens a **new separate** position (up to `max_open_positions=3`), it does not close
  the prior one. `b)`, no opposing-signal logic exists anywhere in the repo
  (grep for `opposing|reverse_signal|close_position` finds only the evaluator's own
  `_close_position`).

### 1.6 Maximum holding period (does not exist post-entry)

- `expiration_config.max_candles=100` is a **setup** lifetime and only counts while the
  setup is `WAITING_FOR_ZONE`/`WAITING_FOR_CONFIRMATION`. It does not apply once
  confirmed. There is **no** time-based or bars-held exit for an open trade anywhere in
  the execution path.

### 1.7 End-of-data exit (implemented)

- `_drain_open_positions` (`evaluator.py:933`) closes any still-open position at the
  last candle's **close** with `TradeExitReason.END_OF_DATA`. This is a data-boundary
  artifact, **not** a profit-taking policy. It is the source of every "winning" trade in
  the current report (see §2).

### 1.8 Costs and intrabar resolution (does not exist)

- P&L is `volume * (exit - entry)` for buys / `volume * (entry - exit)` for sells
  (`default_calc_profit`, `evaluator.py:123`). **No spread, commission, or swap.**
  The entry quote is synthesized with `bid == ask == close` and `spread_points=0`
  (`_make_quote`, `evaluator.py:768`), so the risk engine's spread check always passes.
- `execution_cost_allowance_percent` defaults to `0` and is only used to trim the risk
  budget, not to deduct costs.
- Exits are decided only from each candle's high/low; there is **no tick path**. When a
  single candle contains both the stop and a take-profit level, the evaluator tests
  **take-profit first** (`evaluator.py:868`) — an optimistic same-candle tie-break.
  With `tp_policy="none"` this tie-break is currently moot but becomes material for any
  TP policy.

### 1.9 Implemented vs. not implemented (summary)

| Aspect | Status |
|---|---|
| Entry on confirmed candle close, one per setup | Implemented |
| Structural stop loss, high/low test | Implemented |
| Duplicate-entry prevention, direction mapping | Implemented (preserve) |
| Risk gating (sizing, daily loss, drawdown, stop distance) | Implemented |
| Take-profit branch | Implemented but **inert** (`tp_policy="none"`) |
| `fixed_rr` take profit | Implemented, not enabled |
| Fib-extension take profit | Not implemented (levels are computed and reported) |
| Setup invalidation / expiry as an exit | Enum + branches exist, **unreachable** after entry |
| Opposing-signal / reversal exit | Does not exist |
| Time-based / max-holding exit | Does not exist |
| Trailing stop / break-even / partial exits | Does not exist |
| Spread, commission, swap, slippage | Not modelled |
| Tick-level intrabar ordering | Not modelled (optimistic TP-first tie-break) |

---

## 2. What the current six-month run actually shows

Run `xauusd_20260414_20261014_4eea7638`, `strategy_fingerprint=4eea76386812`,
`tp_policy="none"`. Exit-reason counts parsed from the per-timeframe JSON:

| TF | trades | stop_loss | end_of_data | winning trades | all wins are EOD? |
|---|---|---|---|---|---|
| M1 | 335 | 332 | 3 | 3 | yes |
| M5 | 64 | 61 | 3 | 3 | yes |
| M15 | 46 | 45 | 1 | 1 | yes |
| M30 | 31 | 31 | 0 | 0 | — |
| H1 | 5 | 5 | 0 | 0 | — |
| H4 | 0 | — | — | 0 | — |
| D1 | 0 | — | — | 0 | — |

M1 metrics (`M1.json`): `trade_count=335`, `winning_trades=3`, `losing_trades=332`,
`win_rate=0.009`, `profit_factor=0.3536`, `total_net_pnl=-49264.0`,
`average_holding_bars=589.8`, `avg_rr_ratio=null`.

Interpretation (deliberately not a profitability claim):

- Every losing trade is a stop loss; **every "win" is a position that was never closed by
  any policy** — it was marked to the last available close by the end-of-data drain
  (e.g. M1 sell entered 2026-09-18 at 4396.34, "exited" 2026-10-14 at 4158.51 with
  `hold_bars=23517`). The reported edge comes entirely from open exposure drift, not
  from a repeatable exit.
- The M1 window is **not** the full six months. `coverage_complete=false`,
  `gap_count=78`, `largest_gap_bars=3179`, `missing_bars_estimate=52595`; the terminal's
  M1 history begins `2026-06-30`, and the first ~2.5 months return `empty_candle_data`
  (7 empty-chunk warnings in `load_warnings`).
- Costs are absent (spread/commission/swap), so these numbers are gross mark-to-market
  only.
- **No profitability conclusion should be drawn from these results**, and none of the
  candidate policies below should be ranked using them.

---

## 3. Candidate exit policies (proposals only — nothing implemented)

All options keep the existing entry, stop, sizing and risk gates. For each: exact
conditions, field availability, extra state, look-ahead, same-candle SL/TP handling,
costs, and required tests.

### Option A — Keep the existing stop with no take profit (baseline)

- Entry: unchanged. Exit: stop (high/low test) or end-of-data only.
- Fields: all present (`stop_loss`; `take_profit=None`).
- Extra data/state: none.
- Look-ahead: none introduced; already conservative on entry, optimistic only in the
  (currently moot) same-candle ordering.
- Same-candle SL/TP: N/A (no TP).
- Costs: still absent — must be modelled before any conclusion (see §4).
- Tests: existing SL/EOD tests already cover it; add an explicit assertion that
  `take_profit is None` and `exit_reason ∈ {stop_loss, end_of_data}` under
  `tp_policy="none"`.

### Option B — Take profit at a Fibonacci extension already computed

- Entry: unchanged. Exit: `take_profit = fib_levels.extension_levels[1.272]` (and a
  separately labelled variant for `1.618`), evaluated at entry.
- Exact levels: bullish `high + range*(r-1)`; bearish `low - range*(r-1)`
  (`fibonacci.py:152`). Must be asserted on the correct side of entry before attaching.
- Fields: `FibonacciLevels.extension_levels` already exists and is populated at setup
  creation (`engine.py:484`); the runner already serializes `fib_ext_1.272/1.618`
  (`runner.py:849`). What does **not** exist is plumbing that copies an extension level
  into `TradeIntent`/`RiskAssessment.take_profit`; a small, explicit mapping is required.
- Extra data/state: none beyond the chosen extension ratio (a new labelled research
  parameter). Optionally compare against `R = |entry - stop|`.
- Look-ahead: none — extension levels come only from swings confirmed at or before entry.
  (Do not recompute extensions from later swings.)
- Same-candle SL/TP: currently TP-first (optimistic); must be made an explicit,
  documented choice (see §4).
- Costs: same requirement as A/B — include spread/commission before judging.
- Note on scale: with entry in the 0.5–0.618 zone and the structural stop at the swing
  boundary, a `1.272` extension is roughly ~2.3R and `1.618` roughly ~3.2R (varies with
  where in the zone entry fills). This must be verified per trade, not assumed.
- Tests: extension price correct for buy/sell; TP attached only when on the correct
  side; deterministic exit-reason distribution; no-look-ahead truncation test; same-candle
  tie-break test.

### Option C — Fixed risk/reward targets (1R, 1.5R, 2R) — labelled research scenarios

- Entry: unchanged. Exit: `take_profit = entry ± fixed_rr * |entry - stop|`.
- Fields: **fully implemented already** — `RiskEngine.take_profit_for` and
  `execution_fixed_rr` (`config.py:219`); `assessment.take_profit` flows into
  `BacktestTrade.take_profit` (`evaluator.py:801`). Only configuration + report labelling
  are needed.
- Extra state: none. Each R multiple is a **separate run with its own report directory**.
- Look-ahead: none.
- Same-candle SL/TP: the existing TP-first tie-break applies; must be made explicit.
- Costs: as above.
- Tests: 1R/1.5R/2R TP levels; `rr_ratio` becomes non-null and equals the configured
  multiple for a clean fill; same-candle tie-break; risk sizing `reward_risk_ratio`
  warning present.
- Explicit labelling: outputs must be marked as in-sample research variations of the
  **same** data, never as out-of-sample validation.

### Option D — Exit on an opposing confirmed signal (compatibility caveat)

- Proposed condition: when a new setup on the **same timeframe** confirms in the
  opposite direction of an open position, close that position at the confirming candle's
  close; optionally also on a same-timeframe `CONFIRMED_*` that supersedes the entry's
  impulse.
- Fields: `setup.direction` exists; open positions are already tracked per `setup_id`.
  Missing: a timeframe→open-position link and an explicit "opposing" definition. This is
  **not** compatible with the current lifecycle without new state, because confirmed
  setups are terminal and never emit an opposing event today.
- Extra data/state: per-timeframe open-position tracking; a defined event ordering (must
  the exit be processed before the new entry on the same candle? — yes, to keep
  one-position-per-direction and avoid same-candle double counting).
- Look-ahead: none if the exit uses the same confirming candle close as the existing
  entry convention.
- Same-candle SL/TP: this becomes a third same-candle condition; ordering must be
  defined explicitly (e.g. stop → opposing-close → time, or a stated priority).
- Costs: as above.
- Tests: opposing signal closes the correct position at the confirming close; same-candle
  ordering; non-opposing (same-direction) signal does not close; determinism.

### Option E — Time-based exit — labelled research scenario

- Proposed condition: close at the close of the N-th candle after entry
  (e.g. N ∈ {10, 24, 48} per timeframe), whichever comes first with stop.
- Fields: `entry_candle_index`, `exit_candle_index`, `hold_bars` already exist; candle
  spacing is known (`TIMEFRAMES[tf].seconds`). Missing: a max-holding parameter (new,
  clearly labelled).
- Extra state: a holding counter (derivable from `index - entry_candle_index`).
- Look-ahead: none if exit is at the candle close.
- Same-candle SL/TP: define precedence (recommend stop first for conservatism) and test.
- Costs: as above.
- Tests: exits exactly at `entry_candle_index + N`; stop still wins if hit sooner; EOD
  unchanged; determinism.

---

## 4. Cross-cutting requirements before any policy is chosen

1. **Same-candle SL/TP ordering.** The evaluator currently checks take-profit before stop
   loss (`evaluator.py:868`). Any TP option must state and test the selected rule. Because
   M1 history is incomplete and high-timeframe candles have wide ranges, the conservative
   choice (assume stop first) should be the default and the optimistic choice offered only
   as a labelled sensitivity variant.
2. **Costs.** Spread, commission and swap are absent. Before any comparison, add
   spread (and, where available, commission/swap) at least as a configurable overlay, or
   keep the results explicitly labelled "gross, cost-free".
3. **Intrabar resolution.** Without a complete M1/tick path, TP/SL touching within one
   high-timeframe candle cannot be ordered exactly. Document the assumption and, where
   possible, replay on the highest-resolution data available.
4. **Data quality.** Report `coverage_complete`, gap stats and M1 start date alongside
   every result. Do not treat the current M1 window as representative.
5. **Out-of-sample discipline.** Parameter choices (extension ratio, R multiple, N bars)
   must be fixed on one window and only ever evaluated on a disjoint window that is
   **not** used to select them. Do not select the best target on the same data and call it
   validated.
6. **Safety invariants.** Preserve `trading_enabled=False`, `read_only=True`, use
   `store=None`, keep the direction mapping and the once-per-setup entry, and do not touch
   the live strategy or the execution adapter. Do not weaken or remove tests.
7. **Reproducibility.** Keep byte-for-byte deterministic report output and separate
   report directories per labelled scenario.

### Tests to add (regardless of option)

- Unit tests for each TP level (extension, 1R/1.5R/2R) on both buy and sell.
- Same-candle SL/TP tie-break, for both the conservative and optimistic rule.
- No-look-ahead: truncating the dataset before an exit candle must prevent that exit.
- Exit-reason distribution assertions per policy (no more silent all-`end_of_data` wins).
- `rr_ratio` population when a TP is attached; `avg_rr_ratio` non-null.
- Opposing-signal and time-based ordering tests (Options D/E).
- Determinism (extend the existing byte-for-byte report test to the new scenarios).
- Cost-overlay test (spread subtracted from P&L at entry/exit).

---

## 5. Limitations and non-claims

- This document is an audit and proposal only. Nothing here is implemented or approved.
- The current results are **not** evidence of profitability: every winning trade is an
  end-of-data mark, and the losing trades are all stop losses on a partial, cost-free
  dataset.
- No exit policy can be judged "better" from the same data used to choose it; all
  parameter selection needs a disjoint validation window and modelled costs.

## 6. Recommended next step

Await an explicit decision on a single policy (A–E) and its parameters. No implementation
will begin until one is approved.
