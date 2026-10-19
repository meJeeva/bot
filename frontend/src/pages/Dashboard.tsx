import { useEffect, useMemo, useState } from 'react';

import { useCandles, mergeLiveCandles } from '../hooks/useCandles';
import { useExecution } from '../hooks/useExecution';
import { useMarketStream } from '../hooks/useMarketStream';
import { api } from '../services/api';
import type { Candle, ConnectionEventsResponse, HealthResponse, Timeframe } from '../types/market';
import { DashboardView } from './DashboardView';

const HEALTH_POLL_MS = 10_000;

/**
 * Container for the unified dashboard.
 *
 * Owns the data sources and merges them into props for DashboardView. The
 * trading strategies have been removed, so the dashboard reports market data,
 * connection/health and the read-only execution posture only.
 */
export function Dashboard() {
  const { streamState, snapshot, error, lastMessageAt, streamNotice, noticeTimestamp } = useMarketStream();
  const [timeframe, setTimeframe] = useState<Timeframe>('M15');
  const {
    candles: historyCandles,
    series,
    loading: candlesLoading,
    error: candlesError,
    refresh,
  } = useCandles(timeframe);

  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [events, setEvents] = useState<ConnectionEventsResponse | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    const load = async () => {
      try {
        const [nextHealth, nextEvents] = await Promise.all([
          api.health(controller.signal),
          api.mt5Events(10, controller.signal).catch(() => null),
        ]);
        if (!cancelled) {
          setHealth(nextHealth);
          if (nextEvents) {
            setEvents(nextEvents);
          }
        }
      } catch {
        // Diagnostics are best-effort; the live stream is the real indicator.
      }
    };

    void load();
    const timer = window.setInterval(() => {
      void load();
    }, HEALTH_POLL_MS);

    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(timer);
    };
  }, []);

  // Patch the newest bars from the live snapshot into the REST history.
  const candles: Candle[] = useMemo(() => {
    const summary = snapshot?.timeframes?.[timeframe];
    const live = [summary?.latest_closed, summary?.forming].filter(
      (candle): candle is Candle => Boolean(candle),
    );

    if (live.length === 0) {
      return historyCandles;
    }
    return mergeLiveCandles(historyCandles, live);
  }, [historyCandles, snapshot, timeframe]);

  // Execution & risk (read-only)
  const execution = useExecution();

  return (
    <DashboardView
      // Market data
      health={health}
      snapshot={snapshot}
      streamState={streamState}
      streamError={error}
      streamNotice={streamNotice}
      noticeTimestamp={noticeTimestamp}
      lastMessageAt={lastMessageAt}
      events={events}

      // Timeframe & chart
      timeframe={timeframe}
      onTimeframeChange={setTimeframe}
      candles={candles}
      series={series}
      candlesLoading={candlesLoading}
      candlesError={candlesError}
      onRefreshHistory={refresh}

      // Execution & risk
      executionStatus={execution.status}
      riskStatus={execution.risk}
      executionHistory={execution.history}
      executionLoading={execution.loading}
      executionError={execution.error}
      onRefreshExecution={execution.refresh}
    />
  );
}
