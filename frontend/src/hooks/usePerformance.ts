/**
 * Performance reporting state for the dashboard.
 *
 * Reads the backend's read-only `/api/performance/*` endpoints. The fixed
 * preset cards (today / this week / this month) each get their own summary
 * call so every card is a server-computed fact for its own range; the daily
 * table, cumulative chart and trade list follow the user-selected range and
 * filters. The backend caches each computation briefly, so the 30-second
 * refresh cadence stays cheap.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { api, describeError } from '../services/api';
import type {
  DailyPerformanceResponse,
  PerformanceQuery,
  PerformanceSummary,
  PerformanceTradesResponse,
} from '../types/market';

export type PresetKey = 'today' | 'yesterday' | 'd10' | 'd7' | 'd30' | 'week' | 'month' | 'custom';

export interface PerformanceFilterState {
  preset: PresetKey;
  /** Custom-range bounds (YYYY-MM-DD in the reporting timezone). */
  startDate: string;
  endDate: string;
  symbol: string;
  direction: '' | 'buy' | 'sell';
  magic: string;
}

export const DEFAULT_FILTERS: PerformanceFilterState = {
  preset: 'd10',
  startDate: '',
  endDate: '',
  symbol: '',
  direction: '',
  magic: '',
};

const POLL_MS = 30_000;

/** Shape guards: a malformed payload degrades to "not loaded", never crashes a panel. */
function isSummary(value: unknown): value is PerformanceSummary {
  return (
    typeof value === 'object' &&
    value !== null &&
    'data_available' in value &&
    'net_pnl' in value
  );
}

function isDaily(value: unknown): value is DailyPerformanceResponse {
  return (
    typeof value === 'object' &&
    value !== null &&
    Array.isArray((value as { days?: unknown }).days)
  );
}

function isTrades(value: unknown): value is PerformanceTradesResponse {
  return (
    typeof value === 'object' &&
    value !== null &&
    Array.isArray((value as { trades?: unknown }).trades)
  );
}

export interface UsePerformanceResult {
  filters: PerformanceFilterState;
  setFilters: (next: PerformanceFilterState) => void;
  resetFilters: () => void;
  /** Server-computed summaries for the fixed headline cards. */
  today: PerformanceSummary | null;
  week: PerformanceSummary | null;
  month: PerformanceSummary | null;
  /** The user-selected range. */
  rangeSummary: PerformanceSummary | null;
  daily: DailyPerformanceResponse | null;
  trades: PerformanceTradesResponse | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

function buildQuery(filters: PerformanceFilterState): PerformanceQuery {
  const query: PerformanceQuery = {};
  if (filters.preset === 'custom') {
    if (filters.startDate && filters.endDate) {
      query.start = filters.startDate;
      query.end = filters.endDate;
    }
  } else {
    query.preset = filters.preset;
  }
  if (filters.symbol.trim()) {
    query.symbol = filters.symbol.trim();
  }
  if (filters.direction) {
    query.direction = filters.direction;
  }
  if (filters.magic.trim() && !Number.isNaN(Number(filters.magic.trim()))) {
    query.magic = Number(filters.magic.trim());
  }
  return query;
}

export function usePerformance(): UsePerformanceResult {
  const [filters, setFiltersState] = useState<PerformanceFilterState>(DEFAULT_FILTERS);
  const [refreshTick, setRefreshTick] = useState(0);

  const [today, setToday] = useState<PerformanceSummary | null>(null);
  const [week, setWeek] = useState<PerformanceSummary | null>(null);
  const [month, setMonth] = useState<PerformanceSummary | null>(null);
  const [rangeSummary, setRangeSummary] = useState<PerformanceSummary | null>(null);
  const [daily, setDaily] = useState<DailyPerformanceResponse | null>(null);
  const [trades, setTrades] = useState<PerformanceTradesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const setFilters = useCallback((next: PerformanceFilterState) => {
    setFiltersState(next);
  }, []);

  const resetFilters = useCallback(() => {
    setFiltersState(DEFAULT_FILTERS);
  }, []);

  const refresh = useCallback(() => {
    setRefreshTick((tick) => tick + 1);
  }, []);

  const query = useMemo(() => buildQuery(filters), [filters]);
  const customComplete =
    filters.preset !== 'custom' || (Boolean(filters.startDate) && Boolean(filters.endDate));

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const load = async () => {
      if (!customComplete) {
        return;
      }
      setLoading(true);
      try {
        const [nextToday, nextWeek, nextMonth, nextRange, nextDaily, nextTrades] =
          await Promise.all([
            api.performance.summary({ ...query, preset: 'today' }, controller.signal),
            api.performance.summary({ ...query, preset: 'week' }, controller.signal),
            api.performance.summary({ ...query, preset: 'month' }, controller.signal),
            api.performance.summary(query, controller.signal),
            api.performance.daily(query, controller.signal),
            api.performance.trades(query, controller.signal),
          ]);
        if (cancelled) {
          return;
        }
        setToday(isSummary(nextToday) ? nextToday : null);
        setWeek(isSummary(nextWeek) ? nextWeek : null);
        setMonth(isSummary(nextMonth) ? nextMonth : null);
        setRangeSummary(isSummary(nextRange) ? nextRange : null);
        setDaily(isDaily(nextDaily) ? nextDaily : null);
        setTrades(isTrades(nextTrades) ? nextTrades : null);
        setError(null);
      } catch (cause) {
        if (!cancelled && (cause as { name?: string })?.name !== 'AbortError') {
          setError(describeError(cause));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void load();
    const timer = window.setInterval(() => void load(), POLL_MS);

    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(timer);
    };
  }, [query, customComplete, refreshTick]);

  return {
    filters,
    setFilters,
    resetFilters,
    today,
    week,
    month,
    rangeSummary,
    daily,
    trades,
    loading,
    error,
    refresh,
  };
}
