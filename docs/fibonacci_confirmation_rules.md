# Fibonacci Confirmation Logic - Actual Implementation

This document explains the exact rules used by the Fibonacci-only XAUUSD MT5 trading bot to confirm bullish and bearish setups. It is based on a comprehensive audit of the actual implementation, not assumptions or conventional Fibonacci trading practices.

## 1. Plain-English Summary of Strategy's Actual Confirmation Method

The bot confirms Fibonacci setups using a precise, rule-based sequence:

1. **Swing Detection**: Identifies confirmed swing highs/lows using a pivot/fractal method requiring 3 left and 3 right candles, with all right candles closed
2. **Swing Pair Selection**: Finds the most recent alternating swing pair (low→high for bullish, high→low for bearish)
3. **Fibonacci Calculation**: Computes retracement and extension levels from the confirmed swing
4. **Entry Zone Definition**: Uses the 0.500-0.618 retracement range as the entry zone
5. **Zone Entry Monitoring**: Waits for price to interact with (touch or penetrate) the entry zone
6. **Candle Confirmation**: Requires a completed candle that forms a rejection pattern:
   - Bullish: Bullish candle with sufficient lower wick (wick ≥30% of candle range AND wick ≥50% of body) closing at or above zone lower
   - Bearish: Bearish candle with sufficient upper wick meeting same wick requirements closing at or below zone upper
7. **State Transition**: On valid rejection candle, transitions to CONFIRMED_BUY or CONFIRMED_SELL state

This is a strategy condition only - no order is automatically placed. Execution requires separate authorization via the demo trading system.

## 2. Complete Bullish Confirmation Sequence

```
Market candles (M1-M15-M30-H1-H4-D1, independently)
    ↓
Swing Detection (3 left, 3 right confirmation candles)
    ↓
Find most recent confirmed swing low → swing high pair (bullish impulse)
    ↓
Fibonacci Level Calculation:
    Retracement: 0.382, 0.500, 0.618, 0.786, 1.000
    Extension: 1.272, 1.618
    Entry Zone: [high - range×0.618, high - range×0.500] = [lower price, higher price]
    ↓
Setup Creation: MONITORING state
    ↓
Zone Entry Wait: Price must touch/penetrate entry zone
    (candle_interacts_with_zone = TRUE)
    ↓
Confirmation Wait: Completed candle must satisfy:
    • Candle is bullish (close > open)
    • Lower wick ≥ 30% of total candle range (wick/range ≥ 0.3)
    • Lower wick ≥ 50% of candle body (wick/body ≥ 0.5)
    • Candle range overlaps entry zone
    • Close price ≥ zone lower boundary
    • (If configured) Close within entry zone
    • (If configured) Close in bullish direction
    ↓
Transition: WAITING_FOR_CONFIRMATION → CONFIRMED_BUY
    ↓
Result: Strategy condition met (no automatic order placement)
```

## 3. Complete Bearish Confirmation Sequence

```
Market candles (M1-M15-M30-H1-H4-D1, independently)
    ↓
Swing Detection (3 left, 3 right confirmation candles)
    ↓
Find most recent confirmed swing high → swing low pair (bearish impulse)
    ↓
Fibonacci Level Calculation:
    Retracement: 0.382, 0.500, 0.618, 0.786, 1.000
    Extension: 1.272, 1.618
    Entry Zone: [low + range×0.500, low + range×0.618] = [lower price, higher price]
    ↓
Setup Creation: MONITORING state
    ↓
Zone Entry Wait: Price must touch/penetrate entry zone
    (candle_interacts_with_zone = TRUE)
    ↓
Confirmation Wait: Completed candle must satisfy:
    • Candle is bearish (close < open)
    • Upper wick ≥ 30% of total candle range (wick/range ≥ 0.3)
    • Upper wick ≥ 50% of candle body (wick/body ≥ 0.5)
    • Candle range overlaps entry zone
    • Close price ≤ zone upper boundary
    • (If configured) Close within entry zone
    • (If configured) Close in bearish direction
    ↓
Transition: WAITING_FOR_CONFIRMATION → CONFIRMED_SELL
    ↓
Result: Strategy condition met (no automatic order placement)
```

## 4. Swing-Confirmation Rules

A swing point (high or low) is CONFIRMED when:
- **left_candles**: 3 candles to the left must all have lower highs (for swing high) or higher lows (for swing low)
- **right_candles**: 3 candles to the right must all have lower highs (for swing high) or higher lows (for swing low) AND be CLOSED (is_closed == True)
- **Configuration source**: `strategy_swing_left_candles` and `strategy_swing_right_candles` in Settings (both default to 3)
- **Functions**: `detect_swing_highs()`, `detect_swing_lows()`, `detect_confirmed_swings()` in `backend/app/strategy/swing.py`
- **Confirmation timestamp**: Set to the open_time_utc of the last required right candle when all right candles are closed

Unconfirmed swings are filtered out - only confirmed swings proceed to setup creation.

## 5. Fibonacci Calculation and Anchor-Selection Method

**Anchor Selection**:
- Uses the most recent alternating confirmed swing pair from `find_active_swing_pair()` in `swing.py`
- Bullish setup: swing low → swing high (expecting retracement down)
- Bearish setup: swing high → swing low (expecting retracement up)

**Fibonacci Calculation** (`backend/app/strategy/fibonacci.py`):
- **Default retracement ratios**: (0.382, 0.500, 0.618, 0.786, 1.000)
- **Default extension ratios**: (1.272, 1.618)
- **Bullish formula** (swing low → swing high):
  - Retracement: `price = swing_high - (swing_high - swing_low) × ratio`
  - Extension: `price = swing_high + (swing_high - swing_low) × (ratio - 1.0)`
- **Bearish formula** (swing high → swing low):
  - Retracement: `price = swing_low + (swing_high - swing_low) × ratio`
  - Extension: `price = swing_low - (swing_high - swing_low) × (ratio - 1.0)`
- **Entry zone** (`compute_entry_zone`):
  - Default ratios: 0.500 (lower), 0.618 (upper)
  - Bullish zone: [high - range×0.618, high - range×0.500]
  - Bearish zone: [low + range×0.500, low + range×0.618]
  - Always returns (min, max) so zone_lower < zone_upper

## 6. Exact Levels, Thresholds, Candle Requirements, and Configurable Defaults

| Parameter | Location | Default | Source |
|---|---|---|---|
| Swing left candles | `backend/app/config.py:126` | 3 | `strategy_swing_left_candles` |
| Swing right candles | `backend/app/config.py:127` | 3 | `strategy_swing_right_candles` |
| Min swing size points | `backend/app/config.py:128` | None | `strategy_min_swing_size_points` |
| Swing equal highs tolerance | `backend/app/config.py:129` | 0.0 | `strategy_equal_highs_tolerance_points` |
| Fibonacci primary level | `backend/app/config.py:132` | 0.618 | `strategy_zone_primary_level` |
| Zone lower ratio | `backend/app/config.py:133` | 0.500 | `strategy_zone_lower_ratio` |
| Zone upper ratio | `backend/app/config.py:134` | 0.618 | `strategy_zone_upper_ratio` |
| Zone tolerance points | `backend/app/config.py:135` | 0.0 | `strategy_zone_tolerance_points` |
| Min wick to body ratio | `backend/app/config.py:138` | 0.5 | `strategy_min_wick_to_body_ratio` |
| Min wick to range ratio | `backend/app/config.py:139` | 0.3 | `strategy_min_wick_to_range_ratio` |
| Require close in zone | `backend/app/config.py:140` | True | `strategy_require_close_in_zone` |
| Require close direction | `backend/app/config.py:141` | True | `strategy_require_close_direction` |
| Max candles before expiry | `backend/app/config.py:144` | 100 | `strategy_max_candles` |
| Max hours before expiry | `backend/app/config.py:145` | None | `strategy_max_hours` |
| Use structural invalidation | `backend/app/config.py:148` | True | `strategy_use_structural_invalidation` |
| Require closed candle breach | `backend/app/config.py:149` | True | `strategy_require_closed_candle_breach` |
| Structural buffer points | `backend/app/config.py:150` | 0.0 | `strategy_structural_buffer_points` |
| Evaluation interval (seconds) | `backend/app/config.py:153` | 5.0 | `strategy_evaluation_interval_seconds` |

**Candle Requirements for Confirmation** (`backend/app/strategy/confirmation.py`):
- **Must be completed**: `candle.is_closed == True` (checked in analyze functions)
- **Bullish rejection**:
  - Close > open (strictly bullish candle)
  - Lower wick / range ≥ min_wick_to_range_ratio (0.3)
  - Lower wick / body ≥ min_wick_to_body_ratio (0.5)
  - Candle range [low, high] intersects zone [zone_lower, zone_upper]
  - Close ≥ zone_lower (bullish direction)
  - Optional: Close must be within zone (if require_close_in_zone=True)
  - Optional: Close must be in bullish direction (if require_close_direction=True)
- **Bearish rejection**:
  - Close < open (strictly bearish candle)
  - Upper wick / range ≥ min_wick_to_range_ratio (0.3)
  - Upper wick / body ≥ min_wick_to_body_ratio (0.5)
  - Candle range [low, high] intersects zone [zone_lower, zone_upper]
  - Close ≤ zone_upper (bearish direction)
  - Optional: Close must be within zone (if require_close_in_zone=True)
  - Optional: Close must be in bearish direction (if require_close_direction=True)

## 7. Exact Setup Lifecycle States and Their Meanings

| State | Meaning | Transition Conditions |
|---|---|---|
| **NO_SETUP** | No active setup | → MONITORING when confirmed swing pair found |
| **MONITORING** | Swing pair confirmed, waiting for price to enter zone | → WAITING_FOR_ZONE when price enters zone<br>→ NO_SETUP if swing pair invalidated<br>→ INVALIDATED on structural breach |
| **WAITING_FOR_ZONE** | Setup created, price not yet in zone | → WAITING_FOR_CONFIRMATION when candle interacts with zone<br>→ WAITING_FOR_ZONE (reset) if price leaves zone without reaction<br>→ INVALIDATED on structural breach<br>→ EXPIRED if max candles exceeded |
| **WAITING_FOR_CONFIRMATION** | Price in zone, waiting for rejection candle | → CONFIRMED_BUY (bullish) or CONFIRMED_SELL (bearish) on valid rejection candle<br>→ WAITING_FOR_ZONE if price leaves zone without confirmation<br>→ INVALIDATED on structural breach<br>→ EXPIRED if max candles exceeded |
| **CONFIRMED_BUY** | Bullish setup confirmed (TERMINAL) | No further transitions - strategy condition met |
| **CONFIRMED_SELL** | Bearish setup confirmed (TERMINAL) | No further transitions - strategy condition met |
| **INVALIDATED** | Setup invalidated by price action (TERMINAL) | Structural breach: close beyond swing point ± buffer |
| **EXPIRED** | Setup expired due to time/candles (TERMINAL) | Max candles exceeded (`candles_since_creation > max_candles`) |

**Terminal States**: CONFIRMED_BUY, CONFIRMED_SELL, INVALIDATED, EXPIRED
- Once reached, no further state changes occur
- Strategy conditions are met but no order is automatically placed

## 8. List of Conditions the Bot Does NOT Check

Despite common Fibonacci trading practices, the bot does NOT implement:

- **Number of candles for swing confirmation beyond left/right**: Uses fixed left/right candle counts only
- **Minimum swing size beyond configuration**: `strategy_min_swing_size_points` can be set but defaults to None (no minimum)
- **Equal highs/lows tolerance beyond points**: `strategy_equal_highs_tolerance_points` defaults to 0.0 (strict inequality)
- **Volume requirements**: No volume filters applied
- **Momentum/oscillator filters**: No RSI, MACD, stochastic, etc. checks
- **Higher timeframe alignment**: Each timeframe evaluated independently, no cross-timeframe confirmation required
- **Specific candlestick patterns beyond wick/body ratios**: No checking for engulfing, harami, morning/evening star, etc.
- **Price action beyond rejection candle**: No requirement for specific number of candles in zone or consecutive rejections
- **Session/time-of-day filters**: No London/New York/Asia session restrictions
- **Spread filters**: No maximum spread requirements
- **News/event filters**: No economic calendar awareness
- **Minimum risk/reward ratios**: No automatic TP/SL placement or RR calculation for confirmation
- **Volatility filters**: No ATR-based position sizing or volatility checks for confirmation

## 9. Timeframe-Specific Behavior

- **Independent evaluation**: Each of the seven timeframes (M1, M5, M15, M30, H1, H4, D1) maintains its own separate setup state machine
- **No cross-timeframe requirements**: A setup can confirm on any timeframe without confirmation on other timeframes
- **Separate swing detection**: Swing points detected per timeframe using that timeframe's candles
- **Independent entry zones**: Fibonacci levels and entry zones calculated per timeframe from its swing points
- **Individual confirmation**: Each timeframe waits for its own rejection candle on its own chart
- **No synchronization**: Timeframes do not wait for or require agreement from other timeframes

## 10. Difference Between Confirmed Setup, Eligible Trade, Filled Order, and Closed Trade

| Term | Meaning | Determined By |
|---|---|---|
| **Confirmed Setup** | Strategy engine reached CONFIRMED_BUY or CONFIRMED_SELL state | Strategy engine (`CONFIRMED_BUY`/`CONFIRMED_SELL` in setup.state) |
| **Eligible Trade** | Confirmed setup that has passed all execution authorization checks | ExecutionAuthorization armed AND strategy in CONFIRMED state (requires EXECUTION_ENABLED=true, demo account verified, operator armed) |
| **Filled Order** | Order successfully submitted to broker and filled | Execution adapter reports filled order via `record_execution()` with state=FILLED |
| **Closed Trade** | Position closed by SL/TP or manual exit | Execution adapter reports closed position via `record_execution()` with state=CLOSED |

**Critical Distinction**: 
- The strategy engine NEVER places orders
- CONFIRMED_BUY/CONFIRMED_SELL are **strategy conditions only**
- Execution requires separate opt-in via Phase 4 demo trading system
- Even with execution armed, only setups that were confirmed WHILE armed become eligible
- Historical setups confirmed before execution was armed remain strategy-only

## 11. Relevant Source Files, Function Names, and Test References

### Core Implementation Files:
- `backend/app/strategy/swing.py`: Swing detection and confirmation
  - Functions: `detect_swing_highs()`, `detect_swing_lows()`, `detect_confirmed_swings()`, `find_active_swing_pair()`
- `backend/app/strategy/fibonacci.py`: Fibonacci calculations
  - Functions: `calculate_retracement_price()`, `calculate_extension_price()`, `compute_fibonacci_levels()`, `compute_entry_zone()`
- `backend/app/strategy/setup.py`: Setup model and state machine
  - Classes: `FibonacciSetup`, `SetupState`, `SetupDirection`, `ZoneConfig`, `ConfirmationConfig`
  - Methods: `_evaluate_zone_entry()`, `_evaluate_confirmation()`
- `backend/app/strategy/confirmation.py`: Candle confirmation rules
  - Functions: `analyze_bullish_rejection()`, `analyze_bearish_rejection()`, `check_confirmation()`
- `backend/app/strategy/engine.py`: Strategy orchestration
  - Methods: `_advance_setup()`, `_evaluate_zone_entry()`, `_evaluate_confirmation()`
- `backend/app/config.py`: Configuration defaults
  - Fields: All `strategy_*` fields defining thresholds and parameters

### Test Files Verifying Behavior:
- `backend/tests/strategy/test_confirmation.py`: Unit tests for candle rejection logic
- `backend/tests/strategy/test_setup.py`: State machine and transition tests
- `backend/tests/strategy/test_fibonacci.py`: Fibonacci calculation tests
- `backend/tests/strategy/test_swing.py`: Swing detection tests
- `backend/tests/strategy/test_engine.py`: Full strategy engine integration tests
- Specific test functions:
  - `TestZoneAndConfirmationFlow::test_valid_rejection_candle_confirms_buy`
  - `TestZoneAndConfirmationFlow::test_valid_rejection_candle_confirms_sell`
  - `TestConfirmation::test_valid_bullish_rejection`
  - `TestConfirmation::test_valid_bearish_rejection`

## 12. Known Ambiguities or Missing Rules That Cannot Be Verified

### Verified Behavior (No Ambiguity):
- Swing detection requires exactly 3 left/3 right candles with all right candles closed
- Confirmation requires completed candle with specific wick/body ratios
- Entry zone is strictly [0.500, 0.618] retracement by default
- Bullish/bearish rejection logic is exactly as implemented in confirmation.py

### Areas with Potential Ambiguity (but verified from code):
- **Zone interaction definition**: `candle_interacts_with_zone()` returns True if candle's [high, low] range overlaps zone at all (even 1 point touch)
- **Wick ratio calculations**: Uses exact formulas: `lower_wick = min(open, close) - low`, `upper_wick = high - max(open, close)`
- **Body ratio when body ≈ 0**: Handled by checking `body > 0` before division, treats zero body as infinite ratio (still validated)
- **Equality handling**: Swing detection uses strict inequalities by default (`<=` invalidates), configurable tolerance available
- **Missing configuration validation**: All configs validated in Settings.__post_init__ and model validators

### Cannot Be Verified (Truly Missing/Absent):
- No evidence of any hidden confirmation rules beyond those in confirmation.py
- No volume, volatility, or time filters in strategy logic
- No cross-timeframe dependencies or confirmation requirements
- No minimum bars-in-zone requirement before confirmation eligibility
- No requirement for multiple consecutive rejection candles

## Decision Sequence Summary

The actual execution sequence is:
```
Market candles 
    → Swing detection (3 left, 3 right confirmation) 
    → Swing pair selection (most recent alternating) 
    → Fibonacci level & entry zone calculation 
    → Zone entry monitoring (candle_interacts_with_zone) 
    → Rejection candle validation (specific wick/body ratios) 
    → Setup confirmation (CONFIRMED_BUY/SELL) 
    → [Optional: Execution authorization for demo trading]
```

## Source of Truth

All rules are verifiable in the source code:
- Configuration: `backend/app/config.py`
- Swing detection: `backend/app/strategy/swing.py`
- Fibonacci math: `backend/app/strategy/fibonacci.py`
- Setup logic: `backend/app/strategy/setup.py`
- Confirmation rules: `backend/app/strategy/confirmation.py`
- Engine orchestration: `backend/app/strategy/engine.py`
- Tests: `backend/tests/strategy/*`