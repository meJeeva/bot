/**
 * Derives the operational issues the System Health section shows.
 *
 * Kept pure and free of React so it can be tested directly. The rule this
 * enforces: a green-ish surface must never hide a real problem, and repetitive
 * events (many market ticks, repeated errors) are grouped rather than listed
 * one-by-one.
 */

import type {
  ConnectionEventsResponse,
  HealthResponse,
  MarketSnapshot,
  StreamState,
} from '../types/market';
import type { ExecutionStatusOut } from '../types/execution';
import { formatDateTime } from './format';

export type HealthSeverity = 'error' | 'warning' | 'info';

export interface HealthIssue {
  id: string;
  source: string;
  severity: HealthSeverity;
  message: string;
  /** ISO timestamp of the underlying event, when one exists. */
  timestamp?: string | null;
}

export interface HealthInput {
  streamState: StreamState;
  streamError: string | null;
  streamNotice: string | null;
  events: ConnectionEventsResponse | null;
  snapshot: MarketSnapshot | null;
  health: HealthResponse | null;
  candlesError: string | null;
  executionStatus: ExecutionStatusOut | null;
}

const MAX_CONNECTION_ERRORS = 3;

export function collectHealthIssues(input: HealthInput): HealthIssue[] {
  const issues: HealthIssue[] = [];
  const push = (issue: HealthIssue) => issues.push(issue);

  const {
    snapshot,
    streamState,
    streamError,
    streamNotice,
    events,
    health,
    candlesError,
    executionStatus,
  } = input;

  // --- backend / stream -------------------------------------------------
  if (!health && !snapshot) {
    push({
      id: 'backend-unreachable',
      source: 'Backend',
      severity: 'error',
      message: streamError ?? 'The backend is unreachable. No snapshot has been received.',
    });
  }

  if (streamState === 'error') {
    push({
      id: 'stream-error',
      source: 'WebSocket',
      severity: 'error',
      message: streamError ?? 'The market-data stream is in an error state.',
    });
  } else if (streamState === 'reconnecting') {
    push({
      id: 'stream-reconnecting',
      source: 'WebSocket',
      severity: 'warning',
      message: 'The market-data stream is reconnecting.',
    });
  }

  if (streamNotice) {
    push({
      id: 'stream-notice',
      source: 'WebSocket',
      severity: 'warning',
      message: streamNotice,
    });
  }

  if (streamError && streamState !== 'error') {
    push({ id: 'stream-error-last', source: 'WebSocket', severity: 'error', message: streamError });
  }

  // --- MT5 connection ---------------------------------------------------
  const connection = snapshot?.connection ?? null;
  if (connection?.last_connection_error) {
    push({
      id: 'mt5-connection-error',
      source: 'MT5',
      severity: 'error',
      message: connection.last_connection_error,
      timestamp: connection.last_connected_at,
    });
  }

  if (snapshot?.last_error) {
    push({ id: 'snapshot-error', source: 'Backend', severity: 'error', message: snapshot.last_error });
  }

  // --- market data freshness -------------------------------------------
  if (snapshot) {
    if (snapshot.data_status === 'stale') {
      push({
        id: 'market-stale',
        source: 'Market data',
        severity: 'warning',
        message: 'Market data is stale: the newest tick is older than the freshness threshold.',
        timestamp: snapshot.last_market_update,
      });
    } else if (snapshot.data_status === 'unavailable') {
      push({
        id: 'market-unavailable',
        source: 'Market data',
        severity: 'warning',
        message: 'No usable market data is available from the terminal.',
      });
    }
    if (snapshot.quote?.is_stale) {
      push({
        id: 'quote-stale',
        source: 'Quote',
        severity: 'warning',
        message: 'The current quote is stale.',
        timestamp: snapshot.quote.tick_time_utc,
      });
    }
  }

  // --- candle history ---------------------------------------------------
  if (candlesError) {
    push({ id: 'candles-error', source: 'Chart history', severity: 'warning', message: candlesError });
  }

  // --- execution --------------------------------------------------------
  if (executionStatus?.last_error) {
    push({
      id: 'execution-error',
      source: 'Execution',
      severity: 'error',
      message: executionStatus.last_error,
    });
  }
  if (executionStatus?.mode === 'blocked') {
    push({
      id: 'execution-blocked',
      source: 'Execution',
      severity: 'warning',
      message: executionStatus.reasons.length
        ? `Execution is blocked: ${executionStatus.reasons.join(', ')}.`
        : 'Execution is blocked by the backend.',
    });
  }

  // --- recent recorded connection errors (grouped and capped) -----------
  const recordedErrors = events?.errors ?? [];
  if (recordedErrors.length > 0) {
    const shown = recordedErrors.slice(0, MAX_CONNECTION_ERRORS);
    shown.forEach((event, index) => {
      push({
        id: `recorded-error-${index}-${event.timestamp}`,
        source: 'Connection events',
        severity: 'error',
        message: event.error ? `${event.state}: ${event.error}` : event.state,
        timestamp: event.timestamp,
      });
    });
    if (recordedErrors.length > shown.length) {
      push({
        id: 'recorded-errors-more',
        source: 'Connection events',
        severity: 'info',
        message: `${recordedErrors.length - shown.length} earlier connection error(s) recorded. See the event log.`,
      });
    }
  }

  return dedupeAndSort(issues);
}

function dedupeAndSort(issues: HealthIssue[]): HealthIssue[] {
  const seen = new Set<string>();
  const order: Record<HealthSeverity, number> = { error: 0, warning: 1, info: 2 };
  return issues
    .filter((issue) => {
      const key = `${issue.source}:${issue.message}`;
      if (seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    })
    .sort((a, b) => order[a.severity] - order[b.severity]);
}

export function healthIssueCount(issues: HealthIssue[]): number {
  return issues.filter((issue) => issue.severity !== 'info').length;
}

export function formatIssueTimestamp(timestamp: string | null | undefined): string {
  return formatDateTime(timestamp ?? null);
}
