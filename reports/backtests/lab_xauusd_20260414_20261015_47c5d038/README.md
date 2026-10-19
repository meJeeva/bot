# Full-strategy backtest

Run id: `lab_xauusd_20260414_20261015_47c5d038`
Symbol: `XAUUSD`
Window (UTC): 2026-04-14T00:00:00+00:00 .. 2026-10-15T00:00:00+00:00
Start equity: 10,000.00 USD

**Read-only research.** Simulated results only: not broker fills, not live signals. Commission and swap are not modelled; the headline cost is the measured per-bar spread. No profitability claim is made from this sample.

## Summary

| Scope | Scenario | Window | Signals | Approved | Closed | Win rate | PF | Expectancy | Net |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fibonacci | primary | development | 644 | 346 | 222 | 0.25675675675675674 | 0.901316575822733 | -3.5619222972974356 | -790.7467500000307 |
| fibonacci | primary | validation | 644 | 346 | 67 | 0.26865671641791045 | 0.9359826466903179 | -2.119655223880345 | -142.01689999998314 |
| fibonacci | primary | out_of_sample | 644 | 346 | 57 | 0.21052631578947367 | 0.7274391629272352 | -9.718200877193505 | -553.9374500000298 |
| fibonacci | primary | full | 644 | 346 | 346 | 0.2514450867052023 | 0.878772430167104 | -4.296823988439432 | -1486.7011000000437 |
| ema_pullback | primary | development | 159 | 122 | 78 | 0.21794871794871795 | 0.5803669965873732 | -15.582769230768807 | -1215.455999999967 |
| ema_pullback | primary | validation | 159 | 122 | 25 | 0.28 | 0.7325114162495672 | -8.699398000000784 | -217.48495000001958 |
| ema_pullback | primary | out_of_sample | 159 | 122 | 19 | 0.2631578947368421 | 0.600694920422193 | -12.747773684210998 | -242.20770000000897 |
| ema_pullback | primary | full | 159 | 122 | 122 | 0.23770491803278687 | 0.6118845713224971 | -13.730726639344226 | -1675.1486499999955 |
| liquidity_sweep_mss_fvg | primary | development | 1 | 1 | 1 | 0.0 | 0.0 | -50.22000000000502 | -50.22000000000502 |
| liquidity_sweep_mss_fvg | primary | validation | 1 | 1 | 0 |  |  |  | 0 |
| liquidity_sweep_mss_fvg | primary | out_of_sample | 1 | 1 | 0 |  |  |  | 0 |
| liquidity_sweep_mss_fvg | primary | full | 1 | 1 | 1 | 0.0 | 0.0 | -50.22000000000502 | -50.22000000000502 |
| session_breakout_retest | primary | development | 460 | 343 | 205 | 0.17560975609756097 | 0.6344181279255253 | -12.35066682926804 | -2531.886699999948 |
| session_breakout_retest | primary | validation | 460 | 343 | 67 | 0.3582089552238806 | 1.5186536950907306 | 13.569846268656052 | 909.1796999999555 |
| session_breakout_retest | primary | out_of_sample | 460 | 343 | 71 | 0.2535211267605634 | 0.9362539126608901 | -2.078180985915463 | -147.5508499999979 |
| session_breakout_retest | primary | full | 460 | 343 | 343 | 0.22740524781341107 | 0.8389688212136537 | -5.1611016034985155 | -1770.2578499999909 |
| portfolio | primary | development | 1264 | 415 | 258 | 0.2248062015503876 | 0.7528493431851231 | -8.540266279069801 | -2203.3887000000086 |
| portfolio | primary | validation | 1264 | 415 | 76 | 0.3026315789473684 | 1.080068870338767 | 2.2475565789476146 | 170.8143000000187 |
| portfolio | primary | out_of_sample | 1264 | 415 | 81 | 0.2345679012345679 | 0.9085188396348781 | -2.892355555555274 | -234.2807999999772 |
| portfolio | primary | full | 1264 | 415 | 415 | 0.24096385542168675 | 0.8334355715062203 | -5.462301686746909 | -2266.855199999967 |
| fibonacci | conservative | development | 644 | 238 | 153 | 0.27450980392156865 | 1.0048331358848557 | 0.08719673202614533 | 13.341100000000235 |
| fibonacci | conservative | validation | 644 | 238 | 44 | 0.2727272727272727 | 0.9664910732687366 | -0.620046590909143 | -27.282050000002293 |
| fibonacci | conservative | out_of_sample | 644 | 238 | 41 | 0.2682926829268293 | 1.005127808339458 | 0.09585365853605236 | 3.929999999978147 |
| fibonacci | conservative | full | 644 | 238 | 238 | 0.27310924369747897 | 0.9976938195564264 | -0.042062815126150885 | -10.010950000023911 |
| ema_pullback | conservative | development | 159 | 96 | 65 | 0.2153846153846154 | 0.5801138566886249 | -8.086145384615142 | -525.5994499999842 |
| ema_pullback | conservative | validation | 159 | 96 | 21 | 0.2857142857142857 | 0.6826326282916233 | -5.471271428571843 | -114.89670000000869 |
| ema_pullback | conservative | out_of_sample | 159 | 96 | 10 | 0.3 | 0.7767536427920463 | -3.7035700000008047 | -37.03570000000805 |
| ema_pullback | conservative | full | 159 | 96 | 96 | 0.23958333333333334 | 0.6192985330674654 | -7.05762343750001 | -677.531850000001 |
| liquidity_sweep_mss_fvg | conservative | development | 1 | 1 | 1 | 0.0 | 0.0 | -25.11000000000251 | -25.11000000000251 |
| liquidity_sweep_mss_fvg | conservative | validation | 1 | 1 | 0 |  |  |  | 0 |
| liquidity_sweep_mss_fvg | conservative | out_of_sample | 1 | 1 | 0 |  |  |  | 0 |
| liquidity_sweep_mss_fvg | conservative | full | 1 | 1 | 1 | 0.0 | 0.0 | -25.11000000000251 | -25.11000000000251 |
| session_breakout_retest | conservative | development | 460 | 235 | 138 | 0.17391304347826086 | 0.5860984051974256 | -8.062733333333219 | -1112.6571999999842 |
| session_breakout_retest | conservative | validation | 460 | 235 | 46 | 0.34782608695652173 | 1.2101719015060628 | 3.18245217391283 | 146.3927999999902 |
| session_breakout_retest | conservative | out_of_sample | 460 | 235 | 51 | 0.23529411764705882 | 0.7621045902172463 | -4.188200000000016 | -213.59820000000084 |
| session_breakout_retest | conservative | full | 460 | 235 | 235 | 0.22127659574468084 | 0.7244998895127571 | -5.020691914893596 | -1179.862599999995 |
| portfolio | conservative | development | 1264 | 317 | 202 | 0.21287128712871287 | 0.7326132780530724 | -4.931433168316829 | -996.1494999999994 |
| portfolio | conservative | validation | 1264 | 317 | 57 | 0.2631578947368421 | 0.9140093940967713 | -1.451935087719095 | -82.76029999998842 |
| portfolio | conservative | out_of_sample | 1264 | 317 | 58 | 0.2413793103448276 | 0.8924914066193095 | -1.8473129310342806 | -107.14414999998827 |
| portfolio | conservative | full | 1264 | 317 | 317 | 0.22712933753943218 | 0.791354648893381 | -3.7414951104100194 | -1186.053949999976 |

## Files

- `summary.json` (machine summary) / `comparison.csv` (the table above)
- `trades.csv` (complete trade ledger, both scenarios)
- `data_quality.json`, `monthly_breakdown.csv`, `timeframe_breakdown.csv`
- `equity_curve.svg` (equity + drawdown)
- per-strategy `*.json`

## Method

Each live strategy is driven bar-by-bar with a strictly backward window; entries are simulated at the confirming candle's close and exits from the following candle. Same-candle stop/target uses the conservative stop-first rule unless exact-tiling M1 bars prove the target came first.

Chronological split: development 60% / validation 20% / out-of-sample 20% by entry time; rule constants were frozen before evaluation.

## Scenarios

- **primary**: The repository's configured risk policy, entry cap and daily profit target, used unchanged. This is the reference scenario; no setting is overridden.
- **conservative**: Labeled comparison scenario requested by the brief: 0.25% risk per trade, 1% daily loss limit, one open position, at most four new entries per risk day, a 1.5 minimum planned reward/risk and the same $10 daily profit stop. Strategy-specific stop/target/confirmation rules are unchanged; only account-level numbers are tightened.

## Limitations

- One symbol (XAUUSD) and one six-month regime; results do not generalise.
- Simulated trades are hypothetical, not broker fills; they are distinct from live signals, shadow validation and real orders.
- Commission and swap are not modelled in the headline net; cost is the measured per-bar spread.
- The equity/drawdown and daily limits are simulated on gross entry/exit; the per-bar spread is the only cost applied to the running balance.
- A small closed-trade count cannot support a profitability conclusion; insufficient evidence is reported rather than a claim.
- The implemented EMA pullback is single-timeframe (it reads only the timeframe it is evaluated on); the rules doc describes a multi-timeframe variant. The implemented rule is what is tested here.
