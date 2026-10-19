/**
 * Phase 4 demo-execution status for the dashboard (read-only).
 *
 * Fetches the authorization posture, risk state and the durable execution
 * record history from the backend. Never submits, modifies or closes an order -
 * this hook is strictly informational.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { api, describeError } from '../services/api';
import type {
  ExecutionHistoryOut,
  ExecutionStatusOut,
  RiskStatusOut,
} from '../types/execution';

export interface UseExecutionResult {
  status: ExecutionStatusOut | null;
  risk: RiskStatusOut | null;
  history: ExecutionHistoryOut | null;
  error: string | null;
  loading: boolean;
  refresh: () => void;
}

const POLL_MS = 10_000;

export function useExecution(): UseExecutionResult {
  const [status, setStatus] = useState<ExecutionStatusOut | null>(null);
  const [risk, setRisk] = useState<RiskStatusOut | null>(null);
  const [history, setHistory] = useState<ExecutionHistoryOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true); // Start in loading state
  const [nonce, setNonce] = useState(0);

  const controllerRef = useRef<AbortController | null>(null);

  const loadStatus = useCallback(async (signal?: AbortSignal) => {
    try {
      const result = await api.executionStatus(signal);
      setStatus(result);
      setError(null);
    } catch (cause) {
      if (signal?.aborted) {
        return;
      }
      setError(describeError(cause));
    } finally {
      // We don't set loading to false here because we have multiple loads.
      // We'll set loading to false in the effect that waits for all to complete.
    }
  }, []);

  const loadRisk = useCallback(async (signal?: AbortSignal) => {
    try {
      const result = await api.riskStatus(signal);
      setRisk(result);
    } catch (cause) {
      if (signal?.aborted) {
        return;
      }
      // Risk endpoint may not be implemented (501) - that's acceptable.
      // The dashboard still shows what it can.
    } finally {
      // We don't set loading to false here because we have multiple loads.
    }
  }, []);

  const loadHistory = useCallback(async (signal?: AbortSignal) => {
    try {
      const result = await api.executionHistory(signal);
      setHistory(result);
    } catch (cause) {
      if (signal?.aborted) {
        return;
      }
      // History is best-effort; an empty state is shown when unavailable.
    } finally {
      // We don't set loading to false here because we have multiple loads.
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    void loadStatus(controller.signal);
    void loadRisk(controller.signal);
    void loadHistory(controller.signal);
    return () => controller.abort();
  }, [nonce, loadStatus, loadRisk, loadHistory]);

  // We'll use an effect to set loading to false when all three loads have completed at least once.
  // We can track the completion of each load by checking if the data is non-null or error is set.
  // However, we don't have a way to know when each load finishes without modifying the load functions to set a flag.
  // Alternatively, we can set loading to false after the first attempt, regardless of success.
  // We'll do that in the effect above by setting loading to false in the finally block of a promise that wraps all three.
  // Let's change the approach: we'll wrap the three loads in a Promise.all and set loading to false when they all settle.

  useEffect(() => {
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    Promise.all([
      loadStatus(controller.signal),
      loadRisk(controller.signal),
      loadHistory(controller.signal),
    ]).finally(() => {
      if (!controller.signal.aborted) {
        setLoading(false);
      }
    });
    return () => controller.abort();
  }, [nonce, loadStatus, loadRisk, loadHistory]);

  // Periodic refresh for safety-critical state. The interval reuses the same
  // controller as the manual/nonce load so that a user-triggered refresh
  // aborts any in-flight request and prevents conflicting requests.
  useEffect(() => {
    const timer = window.setInterval(() => {
      const controller = controllerRef.current;
      if (controller && !controller.signal.aborted) {
        setLoading(true);
        void loadStatus(controller.signal);
        void loadRisk(controller.signal);
        void loadHistory(controller.signal);
          // We'll set loading to false after these three complete.
          Promise.all([
            loadStatus(controller.signal),
            loadRisk(controller.signal),
            loadHistory(controller.signal),
          ]).finally(() => {
            if (!controller.signal.aborted) {
              setLoading(false);
            }
          });
      }
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [loadStatus, loadRisk, loadHistory]);

  const refresh = useCallback(() => {
    controllerRef.current?.abort();
    setNonce((value) => value + 1);
  }, []);

  return { status, risk, history, error, loading, refresh };
}