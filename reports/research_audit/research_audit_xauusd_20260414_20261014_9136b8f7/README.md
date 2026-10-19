# Strategy research run

Run id: `research_audit_xauusd_20260414_20261014_9136b8f7`
Symbol: `XAUUSD`
Window (UTC): 2026-04-14T00:00:00+00:00 .. 2026-10-14T07:40:23.874553+00:00

**Read-only research.** These are simulated results, not broker fills and not
live Fibonacci signals. Commission and swap are not modelled; cost is per-bar
spread plus a labelled assumption grid. No profitability claim is made.

## Comparison (net, central cost)

| Strategy | Window | Trades | Closed | Win rate | Profit factor | Expectancy | Net P&L |
| --- | --- | --- | --- | --- | --- | --- | --- |
| fibonacci | development | 83 | 82 | 0.0 | 0.0 | -444.78978131998105 | -36472.762068238444 |
| fibonacci | validation | 10 | 10 | 0.0 | 0.0 | -447.46641336997726 | -4474.664133699773 |
| fibonacci | out_of_sample | 22 | 19 | 0.0 | 0.0 | -393.84718599333144 | -7483.096533873298 |
| fibonacci | full | 115 | 111 | 0.0 | 0.0 | -436.3110156379415 | -48430.52273581151 |
| trend_pullback | development | 206 | 206 | 0.3883495145631068 | 1.2053541973504414 | 64.9813922194551 | 13386.16679720775 |
| trend_pullback | validation | 86 | 86 | 0.18604651162790697 | 0.44043381936855996 | -233.46224029117832 | -20077.752665041335 |
| trend_pullback | out_of_sample | 136 | 135 | 0.3851851851851852 | 1.2397024312578953 | 77.12900022434096 | 10412.415030286029 |
| trend_pullback | full | 428 | 427 | 0.34660421545667447 | 1.025748685919869 | 8.71388562635233 | 3720.8291624524445 |
| breakout_retest | development | 3 | 3 | 0.0 | 0.0 | -292.130122456812 | -876.390367370436 |
| breakout_retest | validation | 4 | 4 | 0.25 | 0.5374420644296881 | -88.04678912350704 | -352.18715649402816 |
| breakout_retest | out_of_sample | 2 | 2 | 0.5 | 1.1752745768864674 | 43.86084364334758 | 87.72168728669516 |
| breakout_retest | full | 9 | 9 | 0.2222222222222222 | 0.46645654332954034 | -126.76175961975211 | -1140.855836577769 |

## Files

- `comparison_summary.json` / `comparison_summary.csv`
- `fibonacci.json` (unchanged baseline)
- `trend_pullback.json`, `breakout_retest.json`
- `spread_distribution.json` (measured per-bar spread by timeframe)
- `cost_scenarios.json` / `cost_scenarios.csv` (labelled cost scenarios)
- `trend_pullback_breakdown.json` (instability breakdown)
- `*_trades.csv` per strategy

## Cost basis (audit)

Cost model version: `2`
Point: `0.01` (symbol metadata (symbol_info.point))
Contract size: `100.0`
Spread unit: points; `spread_price = points * point` (converted once).
Round trip: ONE full spread width per closed trade.
Primary scenario: `measured_per_trade` (measured per-trade spread).
Central cost (price units): `0.077967891235175`
Measured spread basis: `measured_mean_per_bar_spread`

Commission and swap are only modelled as labelled ASSUMPTION scenarios and are
excluded from the headline net. A live spread snapshot is not a historical
measurement.
