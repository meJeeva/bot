import { describe, expect, it } from 'vitest';

import { makeCandle } from '../../test/fixtures';
import {
  applyHistory,
  formingCandle,
  latestClosedCandle,
  upsertCandle,
  upsertCandles,
} from '../candles';

const T0 = 1_791_794_700;

describe('upsertCandle', () => {
  it('appends a newer bar', () => {
    const existing = [makeCandle({ time: T0 })];
    const next = upsertCandle(existing, makeCandle({ time: T0 + 900 }));

    expect(next.map((candle) => candle.time)).toEqual([T0, T0 + 900]);
  });

  it('replaces a bar with the same time instead of duplicating it', () => {
    const existing = [makeCandle({ time: T0, close: 100 }), makeCandle({ time: T0 + 900 })];
    const next = upsertCandle(existing, makeCandle({ time: T0, close: 200 }));

    expect(next).toHaveLength(2);
    expect(next[0].close).toBe(200);
  });

  it('keeps the series ordered when a bar arrives out of order', () => {
    const existing = [makeCandle({ time: T0 }), makeCandle({ time: T0 + 1800 })];
    const next = upsertCandle(existing, makeCandle({ time: T0 + 900 }));

    expect(next.map((candle) => candle.time)).toEqual([T0, T0 + 900, T0 + 1800]);
  });

  it('does not mutate the input array', () => {
    const existing = [makeCandle({ time: T0 })];
    upsertCandle(existing, makeCandle({ time: T0 + 900 }));

    expect(existing).toHaveLength(1);
  });

  it('updates a forming bar repeatedly without growing the series', () => {
    let series = [makeCandle({ time: T0, close: 1, is_closed: false })];

    for (const close of [2, 3, 4, 5]) {
      series = upsertCandle(series, makeCandle({ time: T0, close, is_closed: false }));
    }

    expect(series).toHaveLength(1);
    expect(series[0].close).toBe(5);
  });

  it('turns a forming bar into a closed bar in place', () => {
    const series = [makeCandle({ time: T0, is_closed: false })];
    const next = upsertCandle(series, makeCandle({ time: T0, is_closed: true }));

    expect(next).toHaveLength(1);
    expect(next[0].is_closed).toBe(true);
  });
});

describe('upsertCandles', () => {
  it('merges the latest closed bar and the forming bar without duplicates', () => {
    const history = [
      makeCandle({ time: T0 }),
      makeCandle({ time: T0 + 900 }),
      makeCandle({ time: T0 + 1800 }),
    ];
    const summary = [makeCandle({ time: T0 + 1800 }), makeCandle({ time: T0 + 2700, is_closed: false })];

    const next = upsertCandles(history, summary);

    expect(next.map((candle) => candle.time)).toEqual([T0, T0 + 900, T0 + 1800, T0 + 2700]);
  });

  it('is a no-op for an empty update', () => {
    const history = [makeCandle({ time: T0 })];
    expect(upsertCandles(history, [])).toEqual(history);
  });
});

describe('applyHistory', () => {
  it('replaces the series with the fetched history', () => {
    const current = [makeCandle({ time: T0 })];
    const fetched = [makeCandle({ time: T0 + 900 }), makeCandle({ time: T0 + 1800 })];

    const next = applyHistory(current, { candles: fetched });

    expect(next.map((candle) => candle.time)).toEqual([T0 + 900, T0 + 1800]);
  });

  it('keeps live bars newer than the history so a slow response cannot roll back', () => {
    const current = [makeCandle({ time: T0 + 900 }), makeCandle({ time: T0 + 1800, is_closed: false })];
    const fetched = [makeCandle({ time: T0 })];

    const next = applyHistory(current, { candles: fetched });

    expect(next.map((candle) => candle.time)).toEqual([T0, T0 + 900, T0 + 1800]);
    expect(next).toHaveLength(3);
  });

  it('never duplicates the bar that appears in both history and live data', () => {
    const shared = makeCandle({ time: T0 + 900 });
    const current = [shared];
    const fetched = [makeCandle({ time: T0 }), shared];

    const next = applyHistory(current, { candles: fetched });

    expect(next.map((candle) => candle.time)).toEqual([T0, T0 + 900]);
  });

  it('handles an empty history response without wiping the chart', () => {
    const current = [makeCandle({ time: T0 })];
    expect(applyHistory(current, { candles: [] })).toEqual(current);
  });

  it('repeated history refreshes are idempotent', () => {
    const fetched = { candles: [makeCandle({ time: T0 }), makeCandle({ time: T0 + 900 })] };

    let series = applyHistory([], fetched);
    const once = series.map((candle) => candle.time);
    series = applyHistory(series, fetched);
    series = applyHistory(series, fetched);

    expect(series.map((candle) => candle.time)).toEqual(once);
  });
});

describe('candle helpers', () => {
  it('finds the forming bar', () => {
    const series = [makeCandle({ time: T0 }), makeCandle({ time: T0 + 900, is_closed: false })];
    expect(formingCandle(series)?.time).toBe(T0 + 900);
  });

  it('returns null when every bar is closed', () => {
    expect(formingCandle([makeCandle({ time: T0, is_closed: true })])).toBeNull();
  });

  it('finds the latest closed bar, skipping the forming one', () => {
    const series = [
      makeCandle({ time: T0, is_closed: true }),
      makeCandle({ time: T0 + 900, is_closed: true }),
      makeCandle({ time: T0 + 1800, is_closed: false }),
    ];
    expect(latestClosedCandle(series)?.time).toBe(T0 + 900);
  });

  it('handles an empty series', () => {
    expect(formingCandle([])).toBeNull();
    expect(latestClosedCandle([])).toBeNull();
  });
});
