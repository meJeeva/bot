/**
 * Polls `GET /api/auto-trading/status` and owns the existing Start/Stop calls.
 *
 * This is the exact logic that used to live inside `AutoTradingPanel`, lifted
 * one level so several panels can share one poll without multiplying requests.
 * Nothing about the contract changed: the same endpoints, the same 2 s cadence,
 * no automatic start, and a busy flag that prevents repeated submissions.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { api, describeError } from '../services/api';
import type { AutoTradingStatus } from '../types/market';

const DEFAULT_POLL_MS = 2_000;

export interface UseAutoTradingStatusResult {
  status: AutoTradingStatus | null;
  error: string | null;
  busy: boolean;
  start: () => Promise<void>;
  stop: () => Promise<void>;
  refresh: () => Promise<void>;
}

export function useAutoTradingStatus(pollMs: number = DEFAULT_POLL_MS): UseAutoTradingStatusResult {
  const [status, setStatus] = useState<AutoTradingStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const load = useCallback(async () => {
    try {
      const next = await api.autoTrading.status();
      if (mountedRef.current) {
        setStatus(next);
        setError(null);
      }
    } catch (cause) {
      if (mountedRef.current) {
        setError(describeError(cause));
      }
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), pollMs);
    return () => window.clearInterval(timer);
  }, [load, pollMs]);

  const start = useCallback(async () => {
    setBusy(true);
    try {
      const next = await api.autoTrading.start();
      if (mountedRef.current) {
        setStatus(next);
        setError(null);
      }
    } catch (cause) {
      if (mountedRef.current) {
        setError(describeError(cause));
      }
    } finally {
      setBusy(false);
    }
  }, []);

  const stop = useCallback(async () => {
    setBusy(true);
    try {
      const next = await api.autoTrading.stop();
      if (mountedRef.current) {
        setStatus(next);
        setError(null);
      }
    } catch (cause) {
      if (mountedRef.current) {
        setError(describeError(cause));
      }
    } finally {
      setBusy(false);
    }
  }, []);

  return { status, error, busy, start, stop, refresh: load };
}
