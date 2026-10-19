import { formatDateTime } from '../services/format';
import type { ConnectionEventsResponse, MarketSnapshot } from '../types/market';

export interface EventLogPanelProps {
  events: ConnectionEventsResponse | null;
  snapshot: MarketSnapshot | null;
  streamNotice: string | null;
  lastMessageAt: string | null;
  streamError: string | null;
  noticeTimestamp: string | null;
}

const MAX_EVENT_DISPLAY = 50;

/**
 * Phase 5 — operational event log.
 *
 * Consolidated panel showing backend events: MT5 connection changes,
 * strategy setup lifecycle, replay state transitions, risk limit warnings,
 * and execution authorization changes.
 */
export function EventLogPanel({
  events,
  snapshot,
  streamNotice,
  lastMessageAt,
  streamError,
  noticeTimestamp,
}: EventLogPanelProps) {
  const connection = snapshot?.connection ?? null;

  // Gather all operational events from snapshot connection, strategy, and execution
  const operationalEvents: Array<{
    timestamp: string; // raw ISO string for sorting
    timestampLabel: string; // formatted label for display
    category: 'connection' | 'strategy' | 'replay' | 'execution' | 'market';
    severity: 'info' | 'warning' | 'error';
    message: string;
  }> = [];

  // Connection events
  if (connection) {
    if (connection.last_connection_error) {
      operationalEvents.push({
        timestamp: connection.last_connection_error,
        timestampLabel: formatDateTime(connection.last_connection_error),
        category: 'connection',
        severity: 'error',
        message: `MT5 connection error: ${connection.last_connection_error}`,
      });
    }
    if (connection.last_market_data_at) {
      operationalEvents.push({
        timestamp: connection.last_market_data_at,
        timestampLabel: formatDateTime(connection.last_market_data_at),
        category: 'market',
        severity: 'info',
        message: `Last market data: ${connection.last_market_data_at}`,
      });
    }
    if (connection.server_time_offset_seconds !== null) {
      operationalEvents.push({
        timestamp: connection.server_time_offset_seconds.toString(),
        timestampLabel: formatDateTime(connection.server_time_offset_seconds.toString()),
        category: 'connection',
        severity: 'info',
        message: `Server time offset: ${connection.server_time_offset_seconds}s`,
      });
    }
  }

  // Strategy events
  if (events) {
    const setupEvents = events.events
      .filter((e: any) => e.initialized !== undefined || e.connected !== undefined)
      .slice(0, 10);
    setupEvents.forEach((e: any) => {
      operationalEvents.push({
        timestamp: e.timestamp,
        timestampLabel: formatDateTime(e.timestamp),
        category: 'strategy',
        severity: 'info',
        message: `${e.state || e.initialized ? 'setup initialized' : 'setup state change'}: ${e.error || 'ok'}`,
      });
    });
  }

  // Replay events from lastMessageAt
  if (lastMessageAt) {
    operationalEvents.push({
      timestamp: lastMessageAt,
      timestampLabel: formatDateTime(lastMessageAt),
      category: 'replay',
      severity: 'info',
      message: `Last replay activity: ${lastMessageAt}`,
    });
  }

  // Stream notices
  if (streamNotice) {
    const hasBackendNoticeTimestamp = !!noticeTimestamp;
    const timestampLabel = hasBackendNoticeTimestamp
      ? formatDateTime(noticeTimestamp)
      : 'Client-side notice (no backend timestamp)';
    operationalEvents.push({
      timestamp: noticeTimestamp ?? '',
      timestampLabel,
      category: 'market',
      severity: 'warning',
      message: `Stream notice: ${streamNotice}`,
    });
  }

  // Sort by timestamp descending, limit to max
  const sortedEvents = [...operationalEvents]
    .sort((a, b) => {
      // Events without a valid timestamp (empty string) go to the end
      const timeA = a.timestamp ? new Date(a.timestamp).getTime() : -Infinity;
      const timeB = b.timestamp ? new Date(b.timestamp).getTime() : -Infinity;
      return timeB - timeA;
    })
    .slice(0, MAX_EVENT_DISPLAY);

  return (
    <section className="card" aria-labelledby="event-log-heading">
      <header className="card-header">
        <h2 id="event-log-heading">Event log</h2>
        <span className="badge badge-info">
          {sortedEvents.length} events
        </span>
      </header>

      <dl className="kv" data-testid="event-log-list">
        {sortedEvents.length === 0 ? (
          <p className="empty" data-testid="event-log-empty">
            No operational events.
          </p>
        ) : null}

        {sortedEvents.map((event, index) => (
          <div
            key={index}
            className={
              event.severity === 'error' ? 'alert alert-error' :
              event.severity === 'warning' ? 'alert alert-warning' :
              'alert alert-info'
            }
          >
            <dt>{event.category.toUpperCase()} · {event.timestampLabel}</dt>
            <dd>{event.message}</dd>
          </div>
        ))}
      </dl>

      {streamError ? (
        <p className="alert alert-error" data-testid="event-stream-error">
          {streamError}
        </p>
      ) : null}

      {streamNotice ? (
        <p className="alert alert-warning" data-testid="event-stream-notice">
          {streamNotice}
        </p>
      ) : null}
    </section>
  );
}