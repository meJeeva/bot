/**
 * Polls `GET /api/auto-trading/history` for the completed-cycle table.
 *
 * Read-only and frontend-local: the endpoint already existed, this only reads
 * it on a slow cadence. A payload that is not the expected shape degrades to
 * an empty list - never to invented history.
 */

import { useEffect, useState } from 'react';

import { api, describeError } from '../services/api';
import type { AutoTradingHistoryItem } from '../types/market';

const DEFAULT_POLL_MS = 10_000;

function extractItems(payload: unknown): AutoTradingHistoryItem[] {
  if (typeof payload !== 'object' || payload === null) {
    return [];
  }
  const candidate = (payload as { items?: unknown; history?: unknown }).items;
  const source = Array.isArray(candidate)
    ? candidate
    : Array.isArray((payload as { history?: unknown }).history)
      ? (payload as { history: unknown[] }).history
      : [];
  return source.filter(
    (item): item is AutoTradingHistoryItem =>
      typeof item === 'object' && item !== null && 'cycle_id' in item,
  );
}

export interface UseCycleHistoryResult {
  items: AutoTradingHistoryItem[];
  error: string | null;
  loaded: boolean;
}

export function useCycleHistory(pollMs: number = DEFAULT_POLL_MS): UseCycleHistoryResult {
  const [items, setItems] = useState<AutoTradingHistoryItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const load = async () => {
      try {
        const payload = await api.autoTrading.history(controller.signal);
        if (!cancelled) {
          setItems(extractItems(payload));
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
  }, [pollMs]);

  return { items, error, loaded };
}
