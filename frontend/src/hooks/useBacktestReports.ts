/**
 * Read-only access to previously written backtest report runs.
 *
 * The backtest itself runs as a CLI command; this hook only lists and reads the
 * results that already exist on disk. It never starts a backtest and never
 * modifies a report, so runs are never overwritten or mixed.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { api, describeError } from '../services/api';
import type { BacktestReportDetail, BacktestReports } from '../types/backtest';

export interface UseBacktestReportsResult {
  reports: BacktestReports | null;
  loading: boolean;
  error: string | null;
  selectedRunId: string | null;
  detail: BacktestReportDetail | null;
  detailLoading: boolean;
  detailError: string | null;
  selectRun: (runId: string | null) => void;
  refresh: () => void;
}

export function useBacktestReports(): UseBacktestReportsResult {
  const [reports, setReports] = useState<BacktestReports | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [detail, setDetail] = useState<BacktestReportDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const listRequestId = useRef(0);
  const detailRequestId = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    const id = (listRequestId.current += 1);
    setLoading(true);
    void api
      .backtestReports(controller.signal)
      .then((next) => {
        if (id !== listRequestId.current) {
          return;
        }
        setReports(next);
        setError(null);
      })
      .catch((cause) => {
        if (id !== listRequestId.current || controller.signal.aborted) {
          return;
        }
        setError(describeError(cause));
      })
      .finally(() => {
        if (id === listRequestId.current) {
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [nonce]);

  useEffect(() => {
    if (!selectedRunId) {
      detailRequestId.current += 1;
      setDetail(null);
      setDetailError(null);
      setDetailLoading(false);
      return;
    }
    const controller = new AbortController();
    const id = (detailRequestId.current += 1);
    setDetailLoading(true);
    setDetailError(null);
    void api
      .backtestReport(selectedRunId, controller.signal)
      .then((next) => {
        if (id !== detailRequestId.current) {
          return;
        }
        setDetail(next);
      })
      .catch((cause) => {
        if (id !== detailRequestId.current || controller.signal.aborted) {
          return;
        }
        setDetailError(describeError(cause));
      })
      .finally(() => {
        if (id === detailRequestId.current) {
          setDetailLoading(false);
        }
      });
    return () => controller.abort();
  }, [selectedRunId, nonce]);

  const selectRun = useCallback((runId: string | null) => {
    setSelectedRunId(runId);
  }, []);

  const refresh = useCallback(() => setNonce((value) => value + 1), []);

  return {
    reports,
    loading,
    error,
    selectedRunId,
    detail,
    detailLoading,
    detailError,
    selectRun,
    refresh,
  };
}
