# Session Breakout and Retest Strategy - Implementation Rules

This document specifies the exact rules for the Session Breakout and Retest strategy, implemented in `backend/app/strategy/session_breakout_retest.py`.

## 1. Strategy Overview

This strategy trades breakouts of a configured session's opening range with retest confirmation:
- Define the session timezone, start time, and opening range duration
- Calculate the session's high/low range
- Wait for a breakout of that range
- Enter on a retest that confirms the breakout held

All conditions use **completed candles only**; no look-ahead is permitted.

## 2. Key Definitions

- **Session Timezone:** Configured timezone for the session (default: UTC)
- **Session Start:** Time in session timezone when the session begins (default: 08:00)
- **Opening Range:** First N minutes of the session (default: 30 minutes)
- **Permitted Window:** Maximum time after session start during which entries are allowed (default: 240 minutes / 4 hours)
- **Range High/Low:** Max/min of candles with open times within the opening range

## 3. Exact Entry Rules

### Long Setup:

1. **Opening Range Formation:**
   - Collect all completed candles whose session-local open time is within `[session_start, session_start + opening_range_minutes)`
   - Calculate: `range_high = max(highs)`, `range_low = min(lows)`
   - Range must be >= `min_range_points`

2. **Breakout (completed candle):**
   - Candle closes above `range_high` (`close > range_high`)
   - Candle must be within the permitted trading window

3. **Retest (completed candle within window):**
   - Retest candle touches the boundary (`low <= range_high <= high`)
   - Retest candle closes back above: `close > range_high` AND `close > open` (bullish)

4. **Entry:** The retest confirmation candle **close**

### Short Setup (Mirror):

1. Opening range same as above
2. Breakout: candle closes below `range_low`
3. Retest: `low <= range_low <= high` AND `close < range_low` AND `close < open`

## 4. Stop-Loss Placement

- **Long:** `min(retest candle low, range_high) - stop_buffer`
- **Short:** `max(retest candle high, range_low) + stop_buffer`
- Buffer: 20 points default

## 5. Take-Profit and Reward/Risk

- Target: Measured move = `range_high - range_low` (for longs)
- Long: `entry + (range_high - range_low)`
- Short: `entry - (range_low - range_high)`
- Minimum RR: 1.5 (signals below rejected)

## 6. Rejection Conditions

A signal is rejected when:
- Decision candle is outside the session (before session start or after session end)
- Decision candle is outside the permitted window
- Opening range not yet complete (no candles in the range period)
- Opening range too small (< `min_range_points`)
- No breakout occurred yet
- Breakout too old (retest not within `retest_max_candles`)
- Retest doesn't touch boundary
- Retest doesn't confirm (close not on breakout side)
- Stop on wrong side, invalid stop distance, or insufficient RR

## 7. Configuration Parameters

| Parameter | Config Field | Default |
|---|---|---|
| Session timezone | `session_breakout_timezone` | UTC |
| Session start time | `session_breakout_start_time` | 08:00 |
| Opening range (minutes) | `session_breakout_opening_range_minutes` | 30 |
| Permitted window (minutes) | `session_breakout_permitted_window_minutes` | 240 |
| Max candles for retest | `session_breakout_retest_max_candles` | 8 |
| Min range size (points) | `session_breakout_min_range_points` | 0.0 |
| Stop buffer (points) | `session_breakout_stop_buffer_points` | 20.0 |
| Min stop distance (points) | `session_breakout_min_stop_distance_points` | 100.0 |
| Max stop distance (points) | `session_breakout_max_stop_distance_points` | 5000.0 |
| Min reward/risk | `session_breakout_min_reward_risk` | 1.5 |

## 8. No-Look-Ahead Guarantees

- Range calculated only from candles that closed before the range period ended
- Breakout requires a completed candle to confirm
- Retest uses only the decision candle (most recent completed candle)
- Permitted window enforced on each candle
- Target uses the measured range which was fully formed at range close time

## 9. Important Notes

- Session timezone must be explicitly configured (not assumed)
- Range is calculated from the broker timestamp, converted to session timezone
- DST transitions are handled by the `session_time` module
- A breakout move that is excessively large (> permitted) may be rejected

## 10. Source Files

- Implementation: `backend/app/strategy/session_breakout_retest.py`
- Configuration: `backend/app/config.py` (Session Breakout settings)
- Timezone utilities: `backend/app/strategy/session_time.py`
- Tests: `backend/tests/strategy/test_session_breakout.py` (to be created)
