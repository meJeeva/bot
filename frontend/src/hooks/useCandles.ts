/**
 * Fetches and maintains the candle history for the selected timeframe.
 *
 * History comes from REST; the live bar is patched in from the WebSocket
 * snapshot by the dashboard, so the chart never has to refetch on every tick.
 * A periodic refresh re-syncs against the broker.
 *
 * Two hazards are handled here and both have regression tests:
 *
 * 1. **Discarding the initial load.** Resetting series state in a *separate*
 *    effect invalidated the first request, so the chart stayed empty until the
 *    next periodic refresh. The reset now happens inside the fetch effect,
 *    before the request is issued.
 * 2. **Out-of-order responses.** Switching timeframes rapidly can land an old
 *    response after a newer one. Each request carries a monotonic id and a
 *    stale response is dropped.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { api, describeError } from '../services/api';
import { applyHistory, upsertCandles } from '../services/candles';
import type { Candle, CandleSeries, Timeframe } from '../types/market';

const HISTORY_REFRESH_MS = Number(
  (import.meta.env.VITE_HISTORY_REFRESH_MS as string | undefined) ?? 30_000,
);

export interface UseCandlesResult {
  series: CandleSeries | null;
  candles: Candle[];
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useCandles(timeframe: Timeframe, limit = 300): UseCandlesResult {
  const [series, setSeries] = useState<CandleSeries | null>(null);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  // Guards against an out-of-order response overwriting newer data.
  const requestId = useRef(0);
  // Tracks which timeframe the current series belongs to.
  const seriesTimeframe = useRef<Timeframe | null>(null);

  const refresh = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const currentRequest = (requestId.current += 1);

    // Switching timeframe must not leave bars from the previous series on
    // screen. Done here rather than in a separate effect so it cannot
    // invalidate the request that is about to start.
    if (seriesTimeframe.current !== timeframe) {
      seriesTimeframe.current = timeframe;
      setCandles([]);
      setSeries(null);
      setError(null);
    }

    const load = async (): Promise<void> => {
      setLoading(true);
      try {
        const fetched = await api.candles(timeframe, limit, controller.signal);
        if (cancelled || currentRequest !== requestId.current) {
          return;
        }
        setSeries(fetched);
        setCandles((existing) => applyHistory(existing, fetched));
        setError(null);
      } catch (cause) {
        if (cancelled || currentRequest !== requestId.current) {
          return;
        }
        setError(describeError(cause));
      } finally {
        if (!cancelled && currentRequest === requestId.current) {
          setLoading(false);
        }
      }
    };

    void load();

    const timer = window.setInterval(() => {
      void load();
    }, HISTORY_REFRESH_MS);

    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(timer);
    };
  }, [timeframe, limit, nonce]);

  return { series, candles, loading, error, refresh };
}

/**
 * Patch live bars into an existing series.
 *
 * Both the forming bar (repeated updates, same `time`) and a brand-new bar are
 * handled by the shared upsert helper, so a bar can never be duplicated.
 */
export function mergeLiveCandles(existing: Candle[], incoming: Candle[]): Candle[] {
  if (incoming.length === 0) {
    return existing;
  }
  return upsertCandles(existing, incoming);
}
