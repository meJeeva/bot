# MT5 Order Comment Fix - Implementation Summary

## Problem
The auto-trading service was submitting orders with invalid comments that exceeded MT5's character limit, causing immediate order rejection with error `-2 (Invalid "comment" argument)`.

**Error Log:**
```
2026-10-22T16:03:00.014Z | INFO  | app.services.auto_trading | Submitting entry: {... 'comment': 'AUTO_M1_BUY:c0bc051e-1083-4faa-8ad2-1ba33f5835ee-1', ...}
2026-10-22T16:03:00.014Z | ERROR | app.services.auto_trading | order_send returned None; mt5.last_error=-2 (Invalid "comment" argument)
```

## Solution

### 1. Comment Format
Replaced long UUID-based comments with short, deterministic format:
- **Entry orders**: `AU_M1_B1`, `AU_M1_B2`, `AU_M1_B3`, ...
- **Exit orders**: `AU_M1_C1`, `AU_M1_C2`, `AU_M1_C3`, ...

Where:
- `AU` = Auto
- `M1` = M1 timeframe
- `B` = Buy entry
- `C` = Close exit
- Number = cycle counter

### 2. Changes Made

#### backend/app/services/auto_trading.py

**Added comment generation function (line 23-33):**
```python
def _make_comment(prefix: str, counter: int) -> str:
    """Generate a valid MT5 order comment.
    
    MT5 comments must be 31 characters or less. Format: prefix + counter.
    Examples: AU_M1_B1, AU_M1_B99, AU_M1_C1
    """
    comment = f"{prefix}{counter}"
    if len(comment) > 31:
        # Truncate counter digits if needed (should never happen with reasonable cycle counts)
        comment = comment[:31]
    return comment
```

**Updated entry order comment (line 411):**
```python
"comment": _make_comment("AU_M1_B", self._cycle_counter),
```

**Updated exit order comment (line 524):**
```python
"comment": _make_comment("AU_M1_C", self._cycle_counter or 0),
```

**Improved error handling for exit orders (lines 536-544):**
```python
if result is None:
    try:
        last_err = await self.connection.acall(mt5.last_error)
    except Exception:  # noqa: BLE001
        last_err = None
    logger.error("Exit order_send returned None; mt5.last_error=%s", describe_mt5_error(last_err))
    self._last_error = f"Exit order_send returned None; {describe_mt5_error(last_err)}"
    await asyncio.sleep(1.0)
    continue
```

**Added warning logging for exit rejection (line 550):**
```python
logger.warning("Exit rejected: retcode=%s comment=%s", retcode, getattr(result, "comment", None))
```

#### backend/tests/test_auto_trading_comment.py

**Enhanced test coverage:**
1. `test_entry_comment_short` - Validates entry comment format and length
2. `test_exit_comment_short` - Validates exit comment format and length (NEW)
3. `test_comment_format_function` - Unit tests the `_make_comment` helper directly (NEW)

## Test Results

```
============================= test session starts =============================
platform win32 -- Python 3.12.2, pytest-8.4.2, pluggy-1.6.0
tests/test_auto_trading_comment.py::test_entry_comment_short PASSED      [ 33%]
tests/test_auto_trading_comment.py::test_exit_comment_short PASSED       [ 66%]
tests/test_auto_trading_comment.py::test_comment_format_function PASSED  [100%]

============================== 3 passed, 1 warning in 9.48s
```

## Key Features of the Fix

✅ **Short & Valid**: Comments are 8-11 characters max (well under MT5's 31-char limit)
✅ **Deterministic**: Same cycle number always generates same comment
✅ **Human-readable**: Clear prefix indicates purpose (Buy/Close)
✅ **Unique per cycle**: Cycle counter differentiates each trade
✅ **Tested**: Comprehensive tests validate format, length, and behavior
✅ **Better error handling**: Exit orders now properly log `None` results with MT5 error codes
✅ **No UUID dependency**: Session/cycle UUIDs remain in logs and database, not in MT5 comment

## Safety Guarantees Preserved

- ✅ Symbol, volume, risk calculations unchanged
- ✅ Stop-loss/take-profit behavior unchanged
- ✅ Authorization checks unchanged
- ✅ Demo-account safeguards unchanged
- ✅ Execution protections unchanged
- ✅ Position reconciliation unchanged
- ✅ Magic number filtering unchanged

## Files Changed

1. `backend/app/services/auto_trading.py` - Core fix and error handling
2. `backend/tests/test_auto_trading_comment.py` - Enhanced test coverage

## Manual Demo Verification Procedure

**IMPORTANT**: The logs showed you were running outdated code. You must restart the backend service for these changes to take effect.

### Before Testing

1. **Stop the backend service completely**
2. **Restart the backend** to load the new code:
   ```powershell
   cd E:\TP\fibonacci-mt5-bot\backend
   python -m app.main
   ```
3. **Verify the service is using the new code** by checking startup logs

### Demo Account Testing Steps

1. **Ensure MT5 is connected** to a demo account (NEVER use real account for initial testing)

2. **Enable auto-trading in MT5 terminal** (Tools → Options → Expert Advisors → Allow algorithmic trading)

3. **Start auto-trading** via the frontend or API:
   ```bash
   curl -X POST http://localhost:8000/api/auto-trading/start
   ```

4. **Monitor the logs** for the next cycle (wait up to 1 minute):
   - Look for: `Submitting entry: {...}`
   - Verify comment format: `'comment': 'AU_M1_B1'` (or similar)
   - Entry should succeed without the `-2` error

5. **Check MT5 terminal**:
   - Open the Terminal window (View → Terminal)
   - Go to "Trade" tab
   - Verify the position opened
   - Check the position comment shows `AU_M1_B1`

6. **Let the exit execute** (waits ~50-58 seconds):
   - Monitor logs for exit submission
   - Verify comment format: `'comment': 'AU_M1_C1'`
   - Exit should succeed

7. **Stop auto-trading**:
   ```bash
   curl -X POST http://localhost:8000/api/auto-trading/stop
   ```

8. **Review the history**:
   ```bash
   curl http://localhost:8000/api/auto-trading/history
   ```
   - Status should show `filled` → `closed`
   - No `ambiguous` or `failed` statuses

### What to Watch For

✅ **Success indicators:**
- Log shows: `Submitting entry: {...'comment': 'AU_M1_B1'...}`
- No `-2 (Invalid "comment" argument)` error
- `order_send result: retcode=10009` (TRADE_RETCODE_DONE)
- Position appears in MT5 terminal
- Exit completes successfully

❌ **Failure indicators:**
- Still seeing long UUID-based comments → **backend not restarted**
- Still getting `-2` error → **check MT5 terminal/server restrictions**
- `retcode=10027` (Request rejected) → **spread/price issue, not comment**

### Troubleshooting

**If you still see the old long comment format:**
- The backend service was not restarted
- Kill any running Python processes
- Start fresh from the backend directory

**If you get different MT5 errors:**
- Check MT5 terminal is connected
- Verify AutoTrading is enabled
- Check symbol is available
- Verify account has sufficient margin

**If tests pass but live fails:**
- Ensure you're testing on demo account
- Check broker-specific comment length limits (most allow 31 chars)
- Review MT5 terminal logs (Tools → Options → Expert Advisors → Journal)

## Conclusion

The fix replaces invalid long comments with short, valid MT5-compatible format. All existing safeguards remain intact. Session/cycle tracking still uses UUIDs internally; only the MT5 comment field uses the short format.
