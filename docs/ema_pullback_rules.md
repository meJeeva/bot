# EMA Trend Pullback Strategy - Implementation Rules

This document specifies the exact rules for the EMA Trend Pullback strategy, implemented in `backend/app/strategy/ema_pullback.py`.

## 1. Strategy Overview

The EMA Trend Pullback is a multi-timeframe trend-following strategy that:
- Uses H1 EMAs for directional context
- Identifies M15 pullbacks into the EMA zone
- Confirms entries on M5 completed candles

All conditions use **completed candles only**; no look-ahead is permitted.

## 2. Exact Entry Rules

### Long Entry Sequence:
1. **H1 Directional Context (completed H1 candle):**
   - `EMA(fast) > EMA(slow)` (EMA20 > EMA50 by default)
   - The slow EMA is not falling (`slow_EMA >= slow_EMA_prev`)

2. **M15 Pullback Condition (completed M15 candle):**
   - Price trades down to or through `EMA(fast)` (`low <= EMA20 + tolerance`)
   - Price still holds above `EMA(slow)` (`close > EMA50`)
   - This indicates a pullback within the established trend

3. **M5 Confirmation (completed M5 candle):**
   - `close > open` (bullish candle)
   - `close > EMA(fast)` (back above the fast EMA - continuation, not just a cross)

4. **Entry:** The confirming M5 candle **close** price

### Short Entry Sequence (Mirror):
1. **H1:** `EMA(fast) < EMA(slow)` and slow EMA not rising
2. **M15:** Price rallies to `EMA(fast)` (`high >= EMA20 - tolerance`) but stays below `EMA(slow)` (`close < EMA50`)
3. **M5:** `close < open` and `close < EMA(fast)`

## 3. Stop-Loss Placement

- **Long:** `min(low of last N completed M5 candles) - stop_buffer`
- **Short:** `max(high of last N completed M5 candles) + stop_buffer`
- Default `N=5` lookback candles
- Default buffer: 20 points (0.20 for XAUUSD)

## 4. Take-Profit and Reward/Risk

- **Target:** Nearest confirmed structural swing high (for longs) above entry
- **Fallback:** If no structural target, `entry + fallback_RR * risk` (default RR=2.0)
- **Minimum RR:** Configurable (default 1.5) - signals below this are rejected

## 5. Rejection Conditions

A signal is rejected (with reason logged) when:
- No trend context (`EMA(fast) <= EMA(slow)` or wrong slope)
- No pullback to EMA fast (price didn't reach fast EMA)
- Pullback broke through slow EMA (trend invalidated)
- No bullish continuation candle (or bearish for shorts)
- Stop on wrong side of entry (`stop >= entry` for longs)
- Stop distance < `min_stop_distance` or > `max_stop_distance`
- Planned reward/risk < `min_reward_risk`

## 6. Configuration Parameters

| Parameter | Config Field | Default |
|---|---|---|
| Fast EMA period | `ema_pullback_fast_period` | 20 |
| Slow EMA period | `ema_pullback_slow_period` | 50 |
| Pullback tolerance (points) | `ema_pullback_pullback_tolerance_points` | 0.0 |
| Stop lookback (candles) | `ema_pullback_stop_lookback` | 5 |
| Stop buffer (points) | `ema_pullback_stop_buffer_points` | 20.0 |
| Min stop distance (points) | `ema_pullback_min_stop_distance_points` | 100.0 |
| Max stop distance (points) | `ema_pullback_max_stop_distance_points` | 5000.0 |
| Min reward/risk | `ema_pullback_min_reward_risk` | 1.5 |
| Fallback reward/risk | `ema_pullback_fallback_reward_risk` | 2.0 |
| Swing left | `ema_pullback_swing_left` | 2 |
| Swing right | `ema_pullback_swing_right` | 2 |

## 7. No-Look-Ahead Guarantees

- All EMAs computed on completed candles only
- Swing highs/lows for targets use confirmed swings only (right-side candles must be closed)
- Entry is at the confirming candle close, not the next bar open
- Trend context uses the most recent completed H1 bar

## 8. Source Files

- Implementation: `backend/app/strategy/ema_pullback.py`
- Configuration: `backend/app/config.py` (EMA Pullback settings)
- Tests: `backend/tests/strategy/test_ema_pullback.py` (to be created)
