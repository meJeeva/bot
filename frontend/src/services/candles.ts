/**
 * Candle series bookkeeping.
 *
 * The chart receives bars from two sources - a REST history fetch and live
 * WebSocket updates - and they overlap. Both paths go through these helpers so
 * a bar is keyed by its MetaTrader `time` and can never appear twice.
 *
 * They also handle the two cases that trip naive implementations up:
 * * a *forming* bar that updates repeatedly, and
 * * a history refresh that arrives after newer live bars.
 */

import type { Candle, CandleSeries } from '../types/market';

/** Insert or replace a bar, keeping the series ordered by time. */
export function upsertCandle(candles: readonly Candle[], incoming: Candle): Candle[] {
  const index = candles.findIndex((candle) => candle.time === incoming.time);

  if (index >= 0) {
    const next = candles.slice();
    next[index] = incoming;
    return next;
  }

  const last = candles[candles.length - 1];
  if (!last || last.time < incoming.time) {
    return [...candles, incoming];
  }

  return [...candles, incoming].sort((a, b) => a.time - b.time);
}

/** Fold several live bars into the series, newest last. */
export function upsertCandles(candles: readonly Candle[], incoming: readonly Candle[]): Candle[] {
  return incoming.reduce<Candle[]>((acc, candle) => upsertCandle(acc, candle), [...candles]);
}

/**
 * Replace the series with a freshly fetched history.
 *
 * Live bars strictly newer than the newest history bar are preserved, so a
 * slow history response can never roll the chart backwards.
 */
export function applyHistory(
  current: readonly Candle[],
  series: Pick<CandleSeries, 'candles'>,
): Candle[] {
  const history = series.candles;
  if (history.length === 0) {
    return [...current];
  }

  const newestHistoryTime = history[history.length - 1].time;
  const newerLive = current.filter((candle) => candle.time > newestHistoryTime);

  return upsertCandles(history, newerLive);
}

/** The bar currently forming, if the series has one. */
export function formingCandle(candles: readonly Candle[]): Candle | null {
  const last = candles[candles.length - 1];
  return last && !last.is_closed ? last : null;
}

/** The newest definitely-complete bar. */
export function latestClosedCandle(candles: readonly Candle[]): Candle | null {
  for (let index = candles.length - 1; index >= 0; index -= 1) {
    const candle = candles[index];
    if (candle.is_closed) {
      return candle;
    }
  }
  return null;
}
