# Liquidity Sweep + MSS + FVG Strategy - Implementation Rules

This document specifies the exact rules for the Liquidity Sweep + Market Structure Shift + Fair Value Gap strategy, implemented in `backend/app/strategy/liquidity_sweep_mss_fvg.py`.

## 1. Strategy Overview

This is a **sequenced** setup where three conditions must occur in a specific order:
1. Liquidity sweep (stop hunt beyond a known level)
2. Reclaim (price returns to the swept level)
3. Market Structure Shift (break of a prior structural level)
4. Fair Value Gap formation
5. FVG retracement and confirmation

All conditions use **completed candles only**; no look-ahead is permitted.

## 2. Exact Sequence for Long Setup

### Step 1: Liquidity Level Identification
- The liquidity level = the most recent confirmed swing low
- The swing must have been confirmed (right-side candles closed)

### Step 2: Sweep
- A completed candle trades **below** the liquidity level (`low < level`)
- This is the sweep candle (index recorded)

### Step 3: Reclaim
- A later completed candle closes **back above** the level (`close > level`)
- This confirms the sweep was a stop hunt, not a trend change

### Step 4: MSS (Market Structure Shift)
- Find the most recent confirmed swing HIGH that formed BEFORE the sweep
- A completed candle closes **above** that structural high (`close > structural_high`)
- This confirms a market structure shift to bullish

### Step 5: FVG (Fair Value Gap)
- After the MSS, three consecutive completed candles where:
  - `candle[i-2].high < candle[i].low` (gap up)
  - Gap size >= `min_fvg_points`
- The FVG indicates inefficient price movement

### Step 6: FVG Retest and Entry
- A later completed candle trades back into the FVG (`overlaps`)
- Candle closes bullish (`close > open` and `close >= FVG lower`)
- This is the confirmation candle - entry at its close

## 3. Short Setup (Inverse)

1. Liquidity level = most recent confirmed swing high
2. Sweep: candle high > level
3. Reclaim: candle closes back below level
4. MSS: close below prior structural low
5. FVG: `candle[i-2].low > candle[i].high` (gap down), size >= min_fvg_points
6. Entry: candle retraces into FVG, closes bearish

## 4. Stop-Loss Placement

- **Long:** `min(low of all candles from sweep onward) - stop_buffer`
- **Short:** `max(high of all candles from sweep onward) + stop_buffer`
- Buffer: 20 points default

## 5. Take-Profit and Reward/Risk

- Target: `entry + target_RR * risk` (default RR = 2.0)
- Minimum RR: 1.5 (signals below rejected)

## 6. Rejection Conditions

A signal is rejected when:
- No confirmed swing low/high to define liquidity level
- No sweep occurred (price never traded beyond level)
- Swept level not reclaimed
- No prior structural high/low before the sweep
- MSS not confirmed (price never broke structural level)
- No valid FVG formed after MSS
- FVG retest not completed or not confirmed
- Setup age > `max_setup_age_candles` (default 30)
- Stop on wrong side, invalid stop distance, or insufficient RR

## 7. Configuration Parameters

| Parameter | Config Field | Default |
|---|---|---|
| Swing left | `liquidity_sweep_swing_left` | 2 |
| Swing right | `liquidity_sweep_swing_right` | 2 |
| Min FVG size (points) | `liquidity_sweep_min_fvg_points` | 10.0 |
| Max setup age (candles) | `liquidity_sweep_max_setup_age_candles` | 30 |
| Stop buffer (points) | `liquidity_sweep_stop_buffer_points` | 20.0 |
| Min stop distance (points) | `liquidity_sweep_min_stop_distance_points` | 100.0 |
| Max stop distance (points) | `liquidity_sweep_max_stop_distance_points` | 5000.0 |
| Min reward/risk | `liquidity_sweep_min_reward_risk` | 1.5 |
| Target reward/risk | `liquidity_sweep_target_reward_risk` | 2.0 |

## 8. No-Look-Ahead Guarantees

- Liquidity level selection uses confirmed swings only (right-side candles closed)
- Sweep detection uses only completed candles
- MSS uses structural levels confirmed before the sweep
- FVG forms only after MSS is confirmed
- Entry is at the confirming candle close

## 9. Source Files

- Implementation: `backend/app/strategy/liquidity_sweep_mss_fvg.py`
- Configuration: `backend/app/config.py` (Liquidity Sweep settings)
- Tests: `backend/tests/strategy/test_liquidity_sweep.py` (to be created)
