/**
 * Derives the single status the dashboard shows at the top of the page.
 *
 * The rule this exists to enforce: **the dashboard must never show a green
 * "connected" indicator when the backend has no valid, fresh market data.**
 * A terminal can be connected while the tick feed is silent, and that is a
 * stale state, not a healthy one.
 *
 * Kept pure and free of React so it can be tested directly.
 */

import type { MarketSnapshot, StreamState } from '../types/market';
import { formatTime } from './format';

export type OverallState =
  | 'loading'
  | 'live'
  | 'stale'
  | 'reconnecting'
  | 'disconnected'
  | 'error';

export interface OverallStateDescriptor {
  state: OverallState;
  label: string;
  /** Short explanation shown next to the badge. */
  detail: string;
  /** `true` only when genuinely live market data is flowing. */
  healthy: boolean;
}

export function deriveOverallState(
  snapshot: MarketSnapshot | null,
  streamState: StreamState,
): OverallState {
  if (streamState === 'error') {
    return 'error';
  }

  if (!snapshot) {
    return 'loading';
  }

  const connection = snapshot.connection;

  if (connection.state === 'error') {
    return 'error';
  }

  if (connection.reconnecting || connection.state === 'reconnecting') {
    return 'reconnecting';
  }

  if (!connection.mt5_initialized || !connection.terminal_connected) {
    return 'disconnected';
  }

  if (connection.state === 'disconnected') {
    return 'disconnected';
  }

  const quoteIsLive = snapshot.quote !== null && snapshot.quote.freshness === 'live';
  if (snapshot.data_status === 'live' && quoteIsLive) {
    return 'live';
  }

  return 'stale';
}

export function describeOverallState(
  state: OverallState,
  snapshot: MarketSnapshot | null,
): OverallStateDescriptor {
  const connection = snapshot?.connection ?? null;
  const lastError = snapshot?.last_error ?? connection?.last_connection_error ?? null;

  switch (state) {
    case 'loading':
      return {
        state,
        label: 'Connecting',
        detail: 'Waiting for the first snapshot from the Python backend...',
        healthy: false,
      };

    case 'live':
      return {
        state,
        label: 'Live',
        detail: 'Streaming live MetaTrader 5 market data.',
        healthy: true,
      };

    case 'stale':
      return {
        state,
        label: 'Stale data',
        detail:
          lastError ??
          'The terminal is connected but the latest tick is older than the freshness threshold.',
        healthy: false,
      };

    case 'reconnecting':
      return {
        state,
        label: 'Reconnecting',
        detail:
          connection?.next_reconnect_at
            ? `Terminal disconnected. Next retry at ${formatClock(connection.next_reconnect_at)} ` +
              `(attempt ${connection.reconnect_attempts}).`
            : 'Attempting to restore the MetaTrader 5 connection.',
        healthy: false,
      };

    case 'disconnected':
      return {
        state,
        label: 'Disconnected',
        detail: lastError ?? 'Not connected to a MetaTrader 5 terminal.',
        healthy: false,
      };

    case 'error':
    default:
      return {
        state: 'error',
        label: 'Error',
        detail: lastError ?? 'The backend reported an error.',
        healthy: false,
      };
  }
}

function formatClock(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) {
    return iso;
  }
  return formatTime(iso);
}

/** Tailwind-free CSS class for a state badge. */
export function stateBadgeClass(state: OverallState): string {
  return `badge badge-${state}`;
}
