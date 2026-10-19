import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { makeSeries } from '../../test/fixtures';
import type { CandleSeries, Timeframe } from '../../types/market';

const candlesMock = vi.fn();

vi.mock('../../services/api', async () => {
  const actual = await vi.importActual<typeof import('../../services/api')>('../../services/api');
  return {
    ...actual,
    api: {
      ...actual.api,
      candles: (...args: Parameters<typeof actual.api.candles>) => candlesMock(...args),
    },
  };
});

// Imported after the mock so the hook picks up the stubbed client.
const { useCandles } = await import('../useCandles');

afterEach(() => {
  candlesMock.mockReset();
});

describe('useCandles', () => {
  it('applies the initial history fetch to the series', async () => {
    // Regression: the initial response used to be discarded, leaving the chart
    // with only the live bars until the next 30-second refresh.
    const series = makeSeries('M15', 25);
    candlesMock.mockResolvedValue(series);

    const { result } = renderHook(() => useCandles('M15'));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.series).toEqual(series);
    expect(result.current.candles).toHaveLength(25);
    expect(result.current.error).toBeNull();
  });

  it('requests the timeframe and limit it was given', async () => {
    candlesMock.mockResolvedValue(makeSeries('H1', 5));

    const { result } = renderHook(() => useCandles('H1', 120));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(candlesMock).toHaveBeenCalledWith('H1', 120, expect.anything());
  });

  it('reports a failure without throwing', async () => {
    candlesMock.mockRejectedValue(new Error('backend unreachable'));

    const { result } = renderHook(() => useCandles('M15'));

    await waitFor(() => expect(result.current.error).toBe('backend unreachable'));
    expect(result.current.candles).toEqual([]);
  });

  it('clears the previous series when the timeframe changes', async () => {
    const m15 = makeSeries('M15', 10);
    const h4: CandleSeries = { ...makeSeries('H4', 6), timeframe: 'H4' as Timeframe };

    candlesMock.mockResolvedValueOnce(m15);
    const { result, rerender } = renderHook(({ tf }) => useCandles(tf), {
      initialProps: { tf: 'M15' as Timeframe },
    });
    await waitFor(() => expect(result.current.candles).toHaveLength(10));

    candlesMock.mockResolvedValueOnce(h4);
    rerender({ tf: 'H4' });

    await waitFor(() => expect(result.current.series?.timeframe).toBe('H4'));
    expect(result.current.candles).toHaveLength(6);
  });

  it('drops an out-of-order response instead of overwriting newer data', async () => {
    let resolveSlow: (value: CandleSeries) => void = () => {};
    const slow = new Promise<CandleSeries>((resolve) => {
      resolveSlow = resolve;
    });

    candlesMock.mockReturnValueOnce(slow); // first (M1) - resolves late
    candlesMock.mockResolvedValueOnce(makeSeries('H4', 4)); // second (H4) - resolves first

    const { result, rerender } = renderHook(({ tf }) => useCandles(tf), {
      initialProps: { tf: 'M1' as Timeframe },
    });

    rerender({ tf: 'H4' });
    await waitFor(() => expect(result.current.series?.timeframe).toBe('H4'));

    // The stale M1 response now lands; it must be ignored.
    resolveSlow(makeSeries('M1', 99));
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(result.current.series?.timeframe).toBe('H4');
    expect(result.current.candles).toHaveLength(4);
  });

  it('exposes a manual refresh that refetches', async () => {
    candlesMock.mockResolvedValue(makeSeries('M15', 3));

    const { result } = renderHook(() => useCandles('M15'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    const callsAfterMount = candlesMock.mock.calls.length;

    act(() => result.current.refresh());

    await waitFor(() => expect(candlesMock.mock.calls.length).toBeGreaterThan(callsAfterMount));
  });
});
