# Fibonacci Exit-Policy Comparison — Results

Run: `exit_compare_xauusd_20260414_20261014_70ab4988`
Symbol: XAUUSD. Window: 2026-04-14 → 2026-10-14 (end clamped to run time).
Read-only: `trading_enabled=False`, `read_only=True`; no order was submitted.

This report compares three **backtest-only** exit policies over the same
historical data with the existing entry, stop, sizing and risk logic unchanged:

| Scenario | Take profit |
|---|---|
| `baseline` | none (stop-only; existing behaviour) |
| `fib_extension_1.272` | the setup's own `extension_levels[1.272]` |
| `fib_extension_1.618` | the setup's own `extension_levels[1.618]` |

The extension levels are read from the Fibonacci levels the strategy itself
computed for each confirmed swing pair; no anchor or ratio was invented. For a
bullish setup the level is `swing_high + range*(ratio-1)`, for a bearish setup
`swing_low - range*(ratio-1)`.

Companion files in this directory: `baseline.json`, `fib_extension_1.272.json`,
`fib_extension_1.618.json` (full per-trade detail), `comparison_summary.json`,
`comparison_summary.csv`, `cost_sensitivity.csv`, and `*_trades.csv`.

---

## 1. Same-candle handling

When one candle's range contains both the stop and the target, the order is
unknown from the OHLC bar. The evaluator presumes the **stop was hit first**
(conservative). It refines this only with exact-tiling lower-timeframe (M1)
evidence: the target is recorded first only when the M1 bars inside the candle
prove it. M1 is used only to order such conflicts; for the M1 timeframe itself
no lower resolution exists, so stop-first is always used there.

This conflict was **rare**, because the extension targets sit roughly 2.3R
(1.272) / 3.2R (1.618) from the entry while the stop is the swing boundary:

- 1.272: 1 conflict (M1), resolved to stop.
- 1.618: 4 conflicts. Two (M5, in and out of sample) were resolved to **target**
  by M1 evidence; two (M1) resolved to stop.

## 2. Transaction costs

No spread, commission or swap series exists in the historical dataset, so costs
are a labelled assumption, not a measurement:

```
net = gross - cost_price * volume      (round-trip price cost)
```

The terminal's current spread was read once at run time: **46 points × 0.01 =
0.46**, used as the central cost. Sensitivity values `0.0, 0.1, 0.3, 0.46, 0.5,
1.0` are in `cost_sensitivity.csv`. Costs are the dominant variable (see §4).

## 3. Side-by-side, full window, central cost 0.46

Closed trades only (end-of-data marks reported separately). `net` is after the
central cost; `maxDD` is the realized closed-trade drawdown (excludes floating
P&L of open positions).

### M1 — 100,084 candles (coverage incomplete; see §5)
| Scenario | closed | TP | SL | EOD | win% | gross | net | PF | expectancy | maxDD |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 332 | 0 | 332 | 3 | 0.0% | -76,209 | -87,839 | 0.00 | -264.6 | 87,839 |
| 1.272 | 520 | 197 | 323 | 0 | 37.9% | +8,584 | **-14,473** | 0.875 | -27.8 | 16,331 |
| 1.618 | 520 | 157 | 363 | 0 | 30.2% | +9,268 | **-13,808** | 0.894 | -26.6 | 15,501 |

### M5
| Scenario | closed | TP | SL | EOD | win% | gross | net | PF | expectancy | maxDD |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 61 | 0 | 61 | 3 | 0.0% | -25,360 | -27,283 | 0.00 | -447.3 | 27,283 |
| 1.272 | 200 | 74 | 126 | 1 | 37.0% | +5,753 | -1,388 | 0.978 | -6.9 | 8,627 |
| 1.618 | 200 | 56 | 144 | 1 | 28.0% | +3,813 | -3,278 | 0.954 | -16.4 | 11,923 |

### M15
| Scenario | closed | TP | SL | EOD | win% | gross | net | PF | expectancy | maxDD |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 45 | 0 | 45 | 1 | 0.0% | -20,093 | -21,071 | 0.00 | -468.2 | 21,071 |
| 1.272 | 45 | 15 | 30 | 1 | 33.3% | +161 | -930 | 0.941 | -20.7 | 3,601 |
| 1.618 | 45 | 13 | 32 | 1 | 28.9% | +2,498 | **+1,391** | 1.082 | +30.9 | 3,676 |

### M30
| Scenario | closed | TP | SL | EOD | win% | gross | net | PF | expectancy | maxDD |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 31 | 0 | 31 | 0 | 0.0% | -14,409 | -14,910 | 0.00 | -481.0 | 14,910 |
| 1.272 | 31 | 10 | 21 | 0 | 32.3% | -536 | -1,082 | 0.901 | -34.9 | 3,653 |
| 1.618 | 31 | 9 | 22 | 0 | 29.0% | +1,441 | **+891** | 1.077 | +28.8 | 4,140 |

### H1
| Scenario | closed | TP | SL | EOD | win% | gross | net | PF | expectancy | maxDD |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 5 | 0 | 5 | 0 | 0.0% | -2,475 | -2,542 | 0.00 | -508.5 | 2,542 |
| 1.272 | 5 | 0 | 5 | 0 | 0.0% | -2,475 | -2,542 | 0.00 | -508.5 | 2,542 |
| 1.618 | 5 | 0 | 5 | 0 | 0.0% | -2,475 | -2,542 | 0.00 | -508.5 | 2,542 |

### H4 and D1
No confirmed setups produced filled trades in any scenario (H4: 0; D1: 0). No
metrics are reported for these timeframes because the data does not support them.

### Roll-up (all timeframes; sums, central cost 0.46)
| Scenario | trades | closed | TP | SL | EOD | win% | gross | net | PF | expectancy | avg RR |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 481 | 474 | 0 | 474 | 7 | 0.0% | -138,546 | -153,645 | 0.00 | -324.1 | n/a |
| 1.272 | 803 | 801 | 296 | 505 | 2 | 37.0% | +11,488 | -20,416 | 0.902 | -25.5 | 1.91 |
| 1.618 | 803 | 801 | 235 | 566 | 2 | 29.3% | +14,546 | -17,346 | 0.926 | -21.7 | 2.70 |

Two structural points about these numbers:

1. **The baseline has no real winning exits.** All 474 closed baseline trades
   are stop losses; the only positive marks are the 7 positions still open at the
   end of data (marked at the final close, +101,199 combined). Those are not
   exits and are excluded from win rate, profit factor and expectancy.
2. **The take-profit scenarios take more trades** (803 vs 481). A target closes a
   position earlier than the stop would, freeing the `max_open_positions=3`
   capacity so more subsequent signals are filled. The comparison therefore
   differs in trade count as well as in exit rule; this is an inherent property
   of the existing engine, not a modelling choice, and it means the three rows
   are not a pure "same trades, different exit" experiment.

## 4. Cost sensitivity (net closed P&L)

`cost_sensitivity.csv` holds every timeframe; the shape is consistent:

| Scenario / TF | 0.00 | 0.10 | 0.30 | 0.46 | 1.00 |
|---|---|---|---|---|---|
| 1.272 M1 | +8,584 | +3,571 | -6,453 | -14,473 | -41,540 |
| 1.272 M5 | +5,753 | +4,201 | +1,096 | -1,388 | -9,772 |
| 1.272 M15 | +161 | -76 | -550 | -930 | -2,210 |
| 1.272 M30 | -536 | -654 | -892 | -1,082 | -1,722 |
| 1.618 M1 | +9,268 | +4,251 | -5,782 | -13,808 | -40,898 |
| 1.618 M5 | +3,813 | +2,272 | -811 | -3,278 | -11,602 |
| 1.618 M15 | +2,498 | +2,257 | +1,776 | +1,391 | +92 |
| 1.618 M30 | +1,441 | +1,321 | +1,082 | +891 | +246 |

The baseline is insensitive to cost for its *gross* figure (no target) but its
net losses grow with cost. The extension scenarios turn from positive gross to
negative net once a realistic cost is applied on M1/M5; only 1.618 on M15/M30
stays positive, on very small samples (45 and 31 closed trades).

## 5. Historical data limitations

| TF | candles | coverage_complete | first bar (UTC) | notes |
|---|---|---|---|---|
| M1 | 100,084 | **false** | **2026-06-30** | 78 gaps, largest 3,179 bars, ~52,595 missing; 7 empty chunks Apr–Jun |
| M5 | 34,534 | true | 2026-04-14 | 131 gaps (weekend/holiday) |
| M15 | 11,512 | true | 2026-04-14 | 131 gaps |
| M30 | 5,757 | true | 2026-04-14 | 131 gaps |
| H1 | 2,879 | true | 2026-04-14 | 131 gaps |
| H4 | 786 | true | 2026-04-14 | 26 gaps |
| D1 | 130 | true | 2026-04-14 | 26 gaps |

M1 does not cover the first ~2.5 months of the six-month window. Consequences:

- M1 results describe only 2026-06-30 → 2026-10-14, not the full six months.
- The M1 intrabar resolver has no coverage before 2026-06-30, so same-candle
  conflicts there (if any) fall back to the conservative stop-first assumption.
- H4/D1 produced no filled trades at all, so those timeframes contribute nothing
  to the comparison.

## 6. Out-of-sample (chronological split at 2026-08-20T05:43Z)

The tail ~30% was run as a **separate** evaluator pass over `[split, end]`. The
targets (1.272 / 1.618) were fixed before any period was evaluated, so no target
was chosen on the out-of-sample data. Net at central cost 0.46:

| TF | baseline net (closed / EOD mark) | 1.272 net | 1.618 net |
|---|---|---|---|
| M1 | -44,219 (131 SL) / +66,947 | -4,120 (104 TP) | -3,271 (86 TP) |
| M5 | -20,572 (46 SL) / +36,644 | **+2,765** (23 TP) | **+4,030** (18 TP) |
| M15 | -5,521 (11 SL) / +75 | -993 (3 TP) | -1,830 (2 TP) |
| M30 | -4,059 (8 SL) / 0 | -2,591 (1 TP) | -2,193 (1 TP) |
| H1 | 0 (no OOS entries) | 0 | 0 |
| H4 / D1 | 0 | 0 | 0 |

Out-of-sample is **mixed**: the two extension scenarios beat the baseline on M5
and M1, but remain negative on M15 and M30, and the samples are small. The M1
baseline out-of-sample "net incl. marks" is positive (+22,727) only because of
+66,947 of end-of-data marks — again, not real exits.

## 7. Honest conclusion

What the evidence establishes:

- The stop-only baseline is a **net loser on realized exits** in every timeframe
  that traded; its apparent improvement only comes from marking still-open
  positions at the end of data. This is not a take-profit result.
- Adding a Fibonacci-extension take profit raises the win rate (30–38% of closed
  trades hit a target) and produces positive **gross** P&L, and it removes the
  baseline's dependence on end-of-data marks.
- Cost assumptions dominate the outcome. At the live-spread central cost (0.46)
  the extension scenarios are net-negative on M1, M5, M15 and M30 at the sample
  sizes here; at lower assumed costs M1/M5 flip positive.

What the evidence does **not** establish:

- It does **not** show a robustly profitable exit policy. The only positive
  net figures at central cost (1.618 on M15 +1,391 and M30 +891) rest on 45 and
  31 closed trades and do not survive out of sample (M15 OOS -1,830, M30 OOS
  -2,193).
- No claim about which extension ratio is "best" can be made: 1.272 vs 1.618 are
  close on gross, differ in win rate (1.272 higher) and reward (1.618 higher),
  and the differences are within the noise of small samples plus an unknown
  historical cost.
- Results are invalid as a full six-month M1 conclusion (M1 covers only ~3.5
  months) and are gross of realistic commissions/swaps (spread only).

Given the above, no policy change is justified by this evidence. A decision would
need: a reliable historical spread/commission series, complete M1 coverage (or an
explicit decision to trade only the higher timeframes), and a larger out-of-sample
sample for the M15/M30 candidates.

## 8. Method and safety

- Entry, stop, sizing, risk gates, direction mapping and the once-per-setup entry
  logic are reused unchanged. The only backtest change is the take-profit level,
  the conservative same-candle rule, and end-of-data separation in the metrics.
- The baseline scenario reproduces the pre-existing stop-only report exactly
  (same 481 trades: M1 335, M5 64, M15 46, M30 31, H1 5; 474 stop losses, 7
  end-of-data marks).
- No MetaTrader order function is imported or called anywhere in this path; the
  live strategy, execution adapter and setup store are never touched.
- Tests: full suite `863 passed`. New deterministic tests (16) cover baseline
  equivalence, extension-target sourcing, conservative same-candle handling, the
  M1 resolver and its fallbacks, end-of-data separation, cost adjustment, and a
  source scan proving no order-submission tokens exist in the new modules.
