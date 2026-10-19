import {
  CandlestickSeries,
  createChart,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts';
import { useEffect, useRef } from 'react';

import { toChartTime } from '../services/format';
import type { Candle, Timeframe } from '../types/market';

const UP_COLOR = '#22c55e';
const DOWN_COLOR = '#ef4444';
const AXIS_COLOR = 'rgba(148, 163, 184, 0.25)';
const TEXT_COLOR = '#94a3b8';

export interface CandleChartProps {
  candles: Candle[];
  symbol: string | null;
  timeframe: Timeframe;
}

/**
 * Candlestick chart of the selected timeframe.
 *
 * Data is pushed with `setData` from the merged series that `useCandles` and
 * the live stream maintain, so the chart's input is already de-duplicated by
 * bar time. The viewport is only re-fitted when the symbol or timeframe
 * changes, which keeps a live update from yanking the user's zoom.
 *
 * Axis times are true **UTC** (derived from `open_time_utc`), not the raw
 * broker-server values, so the labels match the timestamps shown elsewhere on
 * the dashboard.
 */
export function CandleChart({ candles, symbol, timeframe }: CandleChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const fittedKeyRef = useRef<string>('');

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return undefined;
    }

    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { color: 'transparent' },
        textColor: TEXT_COLOR,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: 'rgba(148, 163, 184, 0.10)' },
        horzLines: { color: 'rgba(148, 163, 184, 0.10)' },
      },
      rightPriceScale: { borderColor: AXIS_COLOR },
      timeScale: { borderColor: AXIS_COLOR, timeVisible: true, secondsVisible: false },
      localization: {
        timeFormatter: (time: number) =>
          `${new Date(time * 1_000).toISOString().replace('T', ' ').slice(0, 19)} UTC`,
      },
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: UP_COLOR,
      downColor: DOWN_COLOR,
      borderUpColor: UP_COLOR,
      borderDownColor: DOWN_COLOR,
      wickUpColor: UP_COLOR,
      wickDownColor: DOWN_COLOR,
    });

    chartRef.current = chart;
    seriesRef.current = series;

    return () => {
      chartRef.current = null;
      seriesRef.current = null;
      chart.remove();
    };
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    const chart = chartRef.current;
    if (!series || !chart) {
      return;
    }

    series.setData(candles.map(toCandleData));

    const key = `${symbol ?? 'unknown'}:${timeframe}`;
    if (key !== fittedKeyRef.current) {
      fittedKeyRef.current = key;
      chart.timeScale().fitContent();
    }
  }, [candles, symbol, timeframe]);

  return (
    <div
      className="chart"
      ref={containerRef}
      data-testid="candle-chart"
      data-candles={candles.length}
      data-symbol={symbol ?? ''}
      data-timeframe={timeframe}
    />
  );
}

function toCandleData(candle: Candle): CandlestickData<UTCTimestamp> {
  return {
    time: toChartTime(candle) as UTCTimestamp,
    open: candle.open,
    high: candle.high,
    low: candle.low,
    close: candle.close,
  };
}
