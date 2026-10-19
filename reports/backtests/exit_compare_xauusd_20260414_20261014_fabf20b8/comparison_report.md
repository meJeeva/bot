# Exit-Policy Comparison — Validation Audit

Run: `exit_compare_xauusd_20260414_20261014_fabf20b8`
Symbol: XAUUSD. Window: 2026-04-14 → 2026-10-14. Central round-trip cost:
**0.46** (a labelled assumption; see §1).
Read-only: `trading_enabled=False`, `read_only=True`; no order was submitted.

This audit (a) verifies the trading-cost model and its units, (b) separates the
portfolio-level comparison from a common-entry diagnostic, and (c) states what
the evidence does and does not support. The earlier report
`exit_compare_xauusd_20260414_20261014_70ab4988` and the original baseline
`xauusd_20260414_20261014_4eea7638` are preserved unchanged.

---

## 1. Trading-cost calculation — verified

### 1.1 What 0.46 means

`0.46` is a **price distance in USD**, not points and not a percentage. With
`point = 0.01`, it equals **46 XAUUSD points**. The cost model is:

```
net = gross - cost_price * volume        applied ONCE per closed trade
gross = volume * (exit_price - entry_price)   (sell mirrored)
```

Because `gross` is `volume * price_move`, subtracting `cost_price * volume` is
exactly equivalent to paying `0.46` of price per unit of volume on the trade.

### 1.2 Was the reported cost one side or a round trip?

**One full spread width per round trip** — the correct total for a market order.
A round trip crosses the spread once in aggregate (enter at ask = mid + s/2,
exit at bid = mid - s/2, total = s). The model charges `s` once, not `2s` and
not `s/2`. The report now states this explicitly (`transaction_costs.sides`).

### 1.3 Does it scale with volume? Yes — linearly and correctly

`cost = cost_price * volume`. The simulated volume is
`risk_budget / stop_distance` (a per-unit size). Since backtest P&L is
`volume * price_move`, the cost also equals
`(spread_price / stop_distance) * risk_budget` in dollars, which is identical to
the real broker cost `spread_price * contract_size * lots` for **any** contract
size (the contract size cancels). So the cost is realistic in USD even though
the backtest folds `contract_size` into `volume`.

### 1.4 Instrument metadata (live XAUUSD, read once at run time)

| Field | Live value | Backtest SymbolSpec |
|---|---|---|
| digits | 2 | 2 |
| point | 0.01 | 0.01 |
| trade_tick_size | 0.01 | 0.01 |
| trade_tick_value / _loss | 0.1 | 1.0 |
| trade_contract_size | 100.0 | 100.0 |
| volume_min / step / max | 0.01 / 0.01 / 100.0 | 0.01 / 0.01 / 100.0 |
| stops_level | none (null) | 30 |
| swap_long / swap_short | -12.6 / -4.6 | not modelled |
| live spread | ~0.44-0.55 (44-55 points) | n/a |

Notes:

- The broker reports `trade_tick_value = 0.1` while `contract_size = 100`
  (0.01 × 100 = $1.0 would be the textbook value). The backtest does **not** use
  `tick_value` for P&L, so this has no effect on results; it only feeds an
  internal cross-check warning that is never recorded. It is documented for
  transparency, not corrected (correcting it would change non-comparison code).
- `stops_level` is fixed at 30 in the simulation, which is *stricter* than the
  live broker and can reject entries the broker would allow. This can only
  reduce the number of entries, equally for all three policies.
- The live spread moved between samples during this review (38 → 44 → 49 → 55
  points), which is exactly why a single snapshot must not be called a
  historical cost.

### 1.5 Spread, commission, swap

- **Spread: modelled** (as the round-trip price cost above).
- **Commission: NOT modelled.** No reliable commission figure exists for this
  account/symbol.
- **Swap/financing: NOT modelled.** This is material and **not neutral**: the
  stop-only baseline holds positions ~320-450 bars on average (often days), while
  the take-profit scenarios hold ~15-23 bars. Omitting swap therefore flatters
  the baseline. The report now states this (`omitted_costs_note`).

### 1.6 Is the report accurate about the assumptions?

Yes, after this audit. The report now records: the model and unit, the
round-trip convention, linear volume scaling, the per-unit volume meaning,
spread-only modelling with commission/swap explicitly excluded, that the cost is
a labelled **assumption** and **not** a measured historical cost
(`is_measured_historical_cost: false`, `reliable_historical_data: false`), and
the live spread observed at run time for reference. There were **no unit errors
to correct** — the arithmetic was already dimensionally consistent with the
existing `default_calc_profit`.

---

## 2. Two separated comparison questions

Both analyses use the same entry signal, stop, sizing and risk logic as the
existing engine; only the exit policy differs. Both are chronologically correct:
exits are computed strictly forward from each entry candle.

### 2A. Portfolio-level comparison (safeguards preserved)

The three policies run as independent simulations with the existing
`max_open_positions=3` limit and all risk gates. Different exits affect position
availability naturally, so the policies take **different numbers of trades**
(baseline 481 vs 803 for the extension policies). Full detail is in
`comparison_summary.csv` / `comparison_summary.json`.

Full window, central cost 0.46, closed trades only:

| TF | Scenario | trades | closed | TP | SL | EOD | win% | gross | net | PF | expectancy |
|---|---|---|---|---|---|---|---|---|---|---|---|
| M1 | baseline | 335 | 332 | 0 | 332 | 3 | 0% | -76,209 | -87,839 | 0.00 | -264.6 |
| M1 | 1.272 | 520 | 520 | 197 | 323 | 0 | 37.9% | +8,584 | -14,473 | 0.875 | -27.8 |
| M1 | 1.618 | 520 | 520 | 157 | 363 | 0 | 30.2% | +9,268 | -13,808 | 0.894 | -26.6 |
| M5 | baseline | 64 | 61 | 0 | 61 | 3 | 0% | -25,360 | -27,283 | 0.00 | -447.3 |
| M5 | 1.272 | 201 | 200 | 74 | 126 | 1 | 37.0% | +5,753 | -1,388 | 0.978 | -6.9 |
| M5 | 1.618 | 201 | 200 | 56 | 144 | 1 | 28.0% | +3,813 | -3,278 | 0.954 | -16.4 |
| M15 | baseline | 46 | 45 | 0 | 45 | 1 | 0% | -20,093 | -21,071 | 0.00 | -468.2 |
| M15 | 1.272 | 46 | 45 | 15 | 30 | 1 | 33.3% | +161 | -930 | 0.941 | -20.7 |
| M15 | 1.618 | 46 | 45 | 13 | 32 | 1 | 28.9% | +2,498 | **+1,391** | 1.08 | +30.9 |
| M30 | baseline | 31 | 31 | 0 | 31 | 0 | 0% | -14,409 | -14,910 | 0.00 | -481.0 |
| M30 | 1.272 | 31 | 31 | 10 | 21 | 0 | 32.3% | -536 | -1,082 | 0.901 | -34.9 |
| M30 | 1.618 | 31 | 31 | 9 | 22 | 0 | 29.0% | +1,441 | **+891** | 1.08 | +28.8 |
| H1 | all | 5 | 5 | 0 | 5 | 0 | 0% | -2,475 | -2,542 | 0.00 | -508.5 |
| H4/D1 | all | 0 | 0 | 0 | 0 | 0 | — | 0 | 0 | — | — |

Roll-up: baseline net -153,645 (EOD mark +101,828); 1.272 net -20,416; 1.618
net -17,346.

### 2B. Common-entry comparison (diagnostic)

To isolate **trade-level exit behaviour**, every policy is evaluated against the
**same predefined set of entries**: the union of entries actually executed by the
three portfolio runs, deduplicated by (entry candle index, direction, entry
price). Each entry is then replayed forward independently, from the same entry
price, stop and volume, for every policy. Exits cannot change which entries are
taken, and no risk gate is disabled in the portfolio simulation — the entries are
only ones the strategy/risk system already produced.

Eligible entries: M1 520, M5 201, M15 46, M30 31, H1 5, H4 0, D1 0 = **803**.

Skipped signals (rejected by risk in the portfolio runs, summed across the three
runs): M1 `max_open_positions` 194, `stop_too_close` 66, `price_drifted` 6; M5
`max_open_positions` 143, `price_drifted` 24; M15 `price_drifted` 90; M30
`price_drifted` 63; H1 `price_drifted` 39; H4 `price_drifted` 15; D1 none.
Because the set is capacity-limited by the portfolio runs, it under-samples
entries a faster-closing policy would additionally have enabled.

Full window, central cost 0.46 (`common_entry_comparison.csv`):

| TF | Policy | entries | closed | TP | SL | EOD | win% | gross | net | PF | expectancy |
|---|---|---|---|---|---|---|---|---|---|---|---|
| M1 | baseline | 520 | 516 | 0 | 516 | 4 | 0% | -130,405 | -150,290 | 0.00 | -291.3 |
| M1 | 1.272 | 520 | 520 | 197 | 323 | 0 | 37.9% | +9,279 | -10,719 | 0.886 | -20.6 |
| M1 | 1.618 | 520 | 520 | 157 | 363 | 0 | 30.2% | +14,302 | -5,696 | 0.946 | -11.0 |
| M5 | baseline | 201 | 196 | 0 | 196 | 5 | 0% | -88,014 | -94,857 | 0.00 | -484.0 |
| M5 | 1.272 | 201 | 200 | 74 | 126 | 1 | 37.0% | +4,463 | -2,489 | 0.960 | -12.4 |
| M5 | 1.618 | 201 | 200 | 56 | 144 | 1 | 28.0% | +2,416 | -4,536 | 0.935 | -22.7 |
| M15 | baseline | 46 | 45 | 0 | 45 | 1 | 0% | -20,093 | -21,071 | 0.00 | -468.2 |
| M15 | 1.272 | 46 | 45 | 15 | 30 | 1 | 33.3% | +336 | -642 | 0.954 | -14.3 |
| M15 | 1.618 | 46 | 45 | 13 | 32 | 1 | 28.9% | +2,536 | **+1,558** | 1.105 | +34.6 |
| M30 | baseline | 31 | 31 | 0 | 31 | 0 | 0% | -14,409 | -14,910 | 0.00 | -481.0 |
| M30 | 1.272 | 31 | 31 | 10 | 21 | 0 | 32.3% | -237 | -737 | 0.926 | -23.8 |
| M30 | 1.618 | 31 | 31 | 9 | 22 | 0 | 29.0% | +1,591 | **+1,090** | 1.104 | +35.2 |
| H1 | all | 5 | 5 | 0 | 5 | 0 | 0% | -2,475 | -2,542 | 0.00 | -508.5 |

Roll-up: baseline 793 closed / net -283,670 (EOD mark +139,692); 1.272 801 / net
-17,130; 1.618 801 / net -10,126.

### 2C. How A and B differ, and why

- **Entry set.** A lets each policy select entries under `max_open_positions`;
  the extension policies close faster and therefore take 803 trades vs the
  baseline's 481. B pins all policies to one 803-entry set, removing that
  capacity interaction.
- **Baseline penalty.** In B the stop-only policy must exit all 803 entries and
  has no way to realise a winner, so its net collapses to -283,670 (it carries
  10 end-of-data marks worth +139,692). A's smaller baseline loss was partly an
  artefact of it taking fewer trades. B shows stop-only's exit behaviour honestly.
- **Ratio choice.** B makes 1.618 clearly less bad than 1.272 on the same entries
  (1.618 records the larger reward per win); A showed them close. On both, 1.618
  is net-positive on M15 and M30 only.
- **Volume.** B fixes one volume per entry (from the first portfolio run that took
  it), so the same entry has identical size for all policies. This is required
  for isolation and is why B's per-policy gross differs from A's.

Both remain free of look-ahead: entries are read at their confirmation candle and
exits are simulated strictly from the following candle onward.

---

## 3. Data integrity

- Preserved: original baseline report and the prior comparison report.
- End-of-data positions are reported separately from stop/target exits in every
  table and are excluded from win rate, profit factor and expectancy.
- M1 history is incomplete and disclosed: 100,084 bars, coverage_complete
  **false**, data starting **2026-06-30** (7 empty chunks Apr-Jun, ~52,595 missing
  bars). M1 results cover ~3.5 months, not six. Same-candle conflicts before
  2026-06-30 have no lower-timeframe evidence and fall back to stop-first.
- The out-of-sample window is a fixed chronological tail (split 2026-08-20,
  ~30%); the targets 1.272/1.618 were fixed before any period was evaluated, so
  no target was chosen on the out-of-sample period. Part B is a full-window
  diagnostic (no separate out-of-sample run).
- No Fibonacci rule, entry, stop-loss, sizing or live-execution code was changed.
  `trading_enabled=False`, `read_only=True`; no MT5 order function is imported or
  called on this path.

## 4. Verification

| Command | Result |
|---|---|
| `python -m pytest tests/backtest/test_exit_policy.py -q` | 25 passed |
| `python -m pytest tests/backtest/test_exit_policy.py::TestCommonEntryDiagnostic tests/backtest/test_exit_policy.py::TestCostModelUnits -q` | 9 passed |
| `python -m pytest tests/backtest -q` | 102 passed |
| `python -m pytest -q` (full backend suite) | **872 passed**, 2 warnings |
| `python -m app.backtest.exit_comparison --start 2026-04-14 --end 2026-10-14 --central-cost 0.46` | run `fabf20b8`, read-only, exit 0 |

The 9 added tests cover: cost is a single round-trip charge, cost scales linearly
with volume, zero cost leaves gross untouched, extension-target lookup, the
forward-only common-entry exit simulator (incl. conservative same-candle and
end-of-data fallbacks), that all policies see the identical common-entry set, and
that the report carries the corrected cost labels.

## 5. Conclusion

- **The cost arithmetic is correct and now correctly described.** There was no
  unit error; `0.46` is 46 points of price charged once per round trip, scaling
  linearly with volume. It is an **assumption**, not a measured historical cost,
  and only spread is modelled — commission and swap are omitted, which favours
  the long-holding baseline.
- **No exit policy is supported by this evidence.**
  - Stop-only is a net loser on realized exits in every timeframe; its only
    positives are end-of-data marks. Evaluated on a common entry set (§2B) it is
    the worst by a wide margin.
  - The Fibonacci extension policies realise winners and dominate stop-only, but
    at the 0.46 assumption both are still net-negative overall (1.272 -20k,
    1.618 -17k in A; -17k / -10k in B).
  - 1.618 is net-positive on M15 (+1,391 A / +1,558 B) and M30 (+891 A / +1,090 B)
    at 0.46, but on only 45 and 31 closed trades, and it does **not** survive out
    of sample (M15 OOS -1,830, M30 OOS -2,193 in A).
- **Costs and data remain uncertain.** The central cost is a single live-spread
  snapshot that drifted 0.38-0.55 during this review; commission and swap are not
  modelled; M1 covers only ~3.5 of 6 months. Small differences between 1.272 and
  1.618 (or between policies) are within this uncertainty. No profitability claim
  should be made, and no exit policy should be adopted on this basis.
