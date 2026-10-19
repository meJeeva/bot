# Strategy research run

Run id: `research_audit_xauusd_20260414_20261014_647d4067`
Symbol: `XAUUSD`
Window (UTC): 2026-04-14T00:00:00+00:00 .. 2026-10-14T08:18:06.728634+00:00

**Read-only research.** These are simulated results, not broker fills and not
live Fibonacci signals. Commission and swap are not modelled; cost is per-bar
spread plus a labelled assumption grid. No profitability claim is made.

## Comparison (net, central cost)

| Strategy | Window | Trades | Closed | Win rate | Profit factor | Expectancy | Net P&L |
| --- | --- | --- | --- | --- | --- | --- | --- |
| fibonacci | development | 83 | 82 | 0.0 | 0.0 | -444.79080068592157 | -36472.84565624557 |
| fibonacci | validation | 10 | 10 | 0.0 | 0.0 | -447.4671398655208 | -4474.671398655208 |
| fibonacci | out_of_sample | 22 | 19 | 0.0 | 0.0 | -393.84804528124096 | -7483.112860343578 |
| fibonacci | full | 115 | 111 | 0.0 | 0.0 | -436.3119812184176 | -48430.62991524435 |
| trend_pullback | development | 206 | 206 | 0.3883495145631068 | 1.205350601671866 | 64.98037818401816 | 13385.95790590774 |
| trend_pullback | validation | 86 | 86 | 0.18604651162790697 | 0.44043220688166795 | -233.46343466636947 | -20077.855381307774 |
| trend_pullback | out_of_sample | 136 | 135 | 0.3851851851851852 | 1.2396984024078448 | 77.1278785565845 | 10412.263605138909 |
| trend_pullback | full | 428 | 427 | 0.34660421545667447 | 1.0257454277332902 | 8.712801240606263 | 3720.3661297388744 |
| breakout_retest | development | 3 | 3 | 0.0 | 0.0 | -292.1317831698911 | -876.3953495096733 |
| breakout_retest | validation | 4 | 4 | 0.25 | 0.5374363665694649 | -88.04844983658613 | -352.1937993463445 |
| breakout_retest | out_of_sample | 2 | 2 | 0.5 | 1.175269562626221 | 43.859652164749036 | 87.71930432949807 |
| breakout_retest | full | 9 | 9 | 0.2222222222222222 | 0.46645265878123376 | -126.7633160585022 | -1140.8698445265197 |

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
Central cost (price units): `0.07798449836596583`
Measured spread basis: `measured_mean_per_bar_spread`

Commission and swap are only modelled as labelled ASSUMPTION scenarios and are
excluded from the headline net. A live spread snapshot is not a historical
measurement.
