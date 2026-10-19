# Strategy research run

Run id: `research_xauusd_20260414_20261014_30e0af1e`
Symbol: `XAUUSD`
Window (UTC): 2026-04-14T00:00:00+00:00 .. 2026-10-14T07:08:04.296058+00:00

**Read-only research.** These are simulated results, not broker fills and not
live Fibonacci signals. Commission and swap are not modelled; cost is per-bar
spread plus a labelled assumption grid. No profitability claim is made.

## Comparison (net, central cost)

| Strategy | Window | Trades | Closed | Win rate | Profit factor | Expectancy | Net P&L |
| --- | --- | --- | --- | --- | --- | --- | --- |
| fibonacci | development | 83 | 82 | 0.0 | 0.0 | -444.78885033727835 | -36472.685727656826 |
| fibonacci | validation | 10 | 10 | 0.0 | 0.0 | -447.46574986459837 | -4474.657498645984 |
| fibonacci | out_of_sample | 22 | 19 | 0.0 | 0.0 | -393.8464012092333 | -7483.081622975433 |
| fibonacci | full | 115 | 111 | 0.0 | 0.0 | -436.31013377728146 | -48430.42484927824 |
| trend_pullback | development | 206 | 206 | 0.3883495145631068 | 1.2053574812807983 | 64.98231833383082 | 13386.357576769147 |
| trend_pullback | validation | 86 | 86 | 0.18604651162790697 | 0.4404352920524728 | -233.46114947325006 | -20077.658854699504 |
| trend_pullback | out_of_sample | 136 | 135 | 0.3851851851851852 | 1.2397061108059495 | 77.13002463886946 | 10412.553326247376 |
| trend_pullback | full | 428 | 427 | 0.34660421545667447 | 1.0257516616201385 | 8.714875991374754 | 3721.25204831702 |
| breakout_retest | development | 3 | 3 | 0.0 | 0.0 | -292.12860573441714 | -876.3858172032513 |
| breakout_retest | validation | 4 | 4 | 0.25 | 0.5374472683270429 | -88.04527240111213 | -352.1810896044485 |
| breakout_retest | out_of_sample | 2 | 2 | 0.5 | 1.1752791564022818 | 43.86193181582985 | 87.7238636316597 |
| breakout_retest | full | 9 | 9 | 0.2222222222222222 | 0.4664600911053865 | -126.76033813067114 | -1140.8430431760403 |

## Files

- `comparison_summary.json` / `comparison_summary.csv`
- `fibonacci.json` (unchanged baseline)
- `trend_pullback.json`, `breakout_retest.json`
- `*_trades.csv` per strategy

## Cost basis

Central cost (price units): `0.07795272401122587`
Measured spread basis: `measured_mean_per_bar_spread`
