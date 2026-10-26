/**
 * Polls `GET /api/market/candles` for one timeframe.
 *
 * Read-only and frontend-local: the endpoint already existed; this only reads
 * it on a cadence and validates the payload. Anything unexpected degrades to
 * "no series" - the chart never draws an invented candle.
 */

import { useEffect, useState } from 'react';

import { api, describeError } from '../services/api';
import type { CandleSeries } from '../types/market';

const DEFAULT_POLL_MS = 5_000;

function isUsableSeries(payload: unknown): payload is CandleSeries {
  return (
    typeof payload === 'object' &&
    payload !== null &&
    Array.isArray((payload as { candles?: unknown }).candles)
  );
}

export interface UseCandlesResult {
  series: CandleSeries | null;
  error: string | null;
  loaded: boolean;
}

export function useCandles(
  timeframe: string,
  limit: number,
  pollMs: number = DEFAULT_POLL_MS,
): UseCandlesResult {
  const [series, setSeries] = useState<CandleSeries | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const load = async () => {
      try {
        const payload = await api.candles(timeframe, limit, controller.signal);
        if (!cancelled) {
          setSeries(isUsableSeries(payload) ? payload : null);
          setError(null);
          setLoaded(true);
        }
      } catch (cause) {
        if (!cancelled) {
          setError(describeError(cause));
          setLoaded(true);
        }
      }
    };

    void load();
    const timer = window.setInterval(() => void load(), pollMs);

    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(timer);
    };
  }, [timeframe, limit, pollMs]);

  return { series, error, loaded };
}
