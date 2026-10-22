# MT5 Order Comment Format

## Overview

MT5 order comments are limited to **31 characters maximum**. This document describes the comment format used by the auto-trading system.

## Format Specification

### Entry Orders (Buy)
```
AU_M1_B{N}
```

**Components:**
- `AU` - Auto (trading system identifier)
- `M1` - M1 timeframe
- `B` - Buy entry
- `{N}` - Cycle counter (1, 2, 3, ...)

**Examples:**
- First cycle: `AU_M1_B1` (8 characters)
- Tenth cycle: `AU_M1_B10` (9 characters)
- Hundredth cycle: `AU_M1_B100` (10 characters)

### Exit Orders (Close)
```
AU_M1_C{N}
```

**Components:**
- `AU` - Auto (trading system identifier)
- `M1` - M1 timeframe
- `C` - Close/exit
- `{N}` - Cycle counter (1, 2, 3, ...)

**Examples:**
- First cycle: `AU_M1_C1` (8 characters)
- Tenth cycle: `AU_M1_C10` (9 characters)
- Hundredth cycle: `AU_M1_C100` (10 characters)

## Length Analysis

| Cycle Count | Entry Comment | Length | Exit Comment | Length |
|-------------|---------------|--------|--------------|--------|
| 1-9         | AU_M1_B1      | 8      | AU_M1_C1     | 8      |
| 10-99       | AU_M1_B10     | 9      | AU_M1_C10    | 9      |
| 100-999     | AU_M1_B100    | 10     | AU_M1_C100   | 10     |
| 1000-9999   | AU_M1_B1000   | 11     | AU_M1_C1000  | 11     |
| 10000+      | AU_M1_B10000  | 12     | AU_M1_C10000 | 12     |

**Maximum reasonable length**: 12 characters (for 99,999 cycles)
**MT5 limit**: 31 characters
**Safety margin**: 19 characters

## Implementation

### Code Location
`backend/app/services/auto_trading.py`

### Function
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

### Usage

**Entry orders:**
```python
request = {
    # ... other fields ...
    "comment": _make_comment("AU_M1_B", self._cycle_counter),
}
```

**Exit orders:**
```python
request = {
    # ... other fields ...
    "comment": _make_comment("AU_M1_C", self._cycle_counter or 0),
}
```

## Design Rationale

### Why Not UUIDs?

The previous implementation used session UUID + cycle ID in comments:
```
AUTO_M1_BUY:c0bc051e-1083-4faa-8ad2-1ba33f5835ee-1
```

This format:
- ❌ Exceeds 31-character MT5 limit (52 characters)
- ❌ Contains special characters that may be rejected
- ❌ Is not human-readable in MT5 terminal
- ❌ Causes immediate order rejection

### Why This Format?

✅ **Compliant**: Well under MT5's 31-character limit
✅ **Deterministic**: Same cycle always generates same comment
✅ **Human-readable**: Clear meaning when viewed in MT5 terminal
✅ **Unique**: Cycle counter differentiates each trade within a session
✅ **Filterable**: Easy to search in MT5 history (e.g., "AU_M1_B*")
✅ **Tested**: Comprehensive unit and integration tests

### Where Is Full Tracking Data?

The short comment is only for MT5's order submission API. Full tracking remains in:

1. **Application logs**: Full session UUID and cycle ID
2. **Database**: Complete trade history with all metadata
3. **Internal state**: Session ID, cycle ID, timestamps, etc.
4. **API responses**: Full structured data returned to clients

The MT5 comment field is intentionally minimal because:
- It has strict length limits
- It's primarily for human reference in the terminal
- It's not meant for programmatic tracking (use magic number instead)

## Magic Number vs Comment

**Magic Number** (`auto_trade_magic_number` config):
- Used for programmatic position filtering
- Identifies all positions from this strategy
- Remains consistent across sessions
- Used by `positions_get()` filtering

**Comment**:
- Human-readable label only
- Not used for filtering or identification
- Changes with each cycle
- Optional field in order requests

## Testing

Tests are in `backend/tests/test_auto_trading_comment.py`:

1. **test_entry_comment_short**: Validates entry comment format
2. **test_exit_comment_short**: Validates exit comment format
3. **test_comment_format_function**: Unit tests the helper function

All tests verify:
- Comment length ≤ 31 characters
- Correct prefix (AU_M1_B or AU_M1_C)
- Expected format for cycle counter

## Future Considerations

If timeframes beyond M1 are added:
- M5: `AU_M5_B1`, `AU_M5_C1`
- M15: `AU_M15_B1`, `AU_M15_C1`
- H1: `AU_H1_B1`, `AU_H1_C1`

All remain well under the 31-character limit.
