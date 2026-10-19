import { formatDateTime } from '../services/format';
import type {
  ConnectionEventsResponse,
  HealthResponse,
  MarketSnapshot,
  StreamState,
} from '../types/market';

export interface AppStatusCardProps {
  streamState: StreamState;
  lastMessageAt: string | null;
  snapshot: MarketSnapshot | null;
  health: HealthResponse | null;
  events: ConnectionEventsResponse | null;
  streamNotice: string | null;
}

const STREAM_LABELS: Record<StreamState, string> = {
  loading: 'connecting',
  connected: 'open',
  reconnecting: 'reconnecting',
  error: 'error',
};

/**
 * Dashboard-level health: the WebSocket link, the last backend update, recent
 * connection errors and an unambiguous statement that trading is disabled.
 */
export function AppStatusCard({
  streamState,
  lastMessageAt,
  snapshot,
  health,
  events,
  streamNotice,
}: AppStatusCardProps) {
  const recentErrors = events?.errors ?? [];

  return (
    <section className="card" aria-labelledby="app-status-heading">
      <header className="card-header">
        <h2 id="app-status-heading">Application status</h2>
        <span className={`badge badge-stream-${streamState}`} data-testid="stream-state">
          {STREAM_LABELS[streamState]}
        </span>
      </header>

      <dl className="kv">
        <div>
          <dt>WebSocket</dt>
          <dd data-testid="ws-state">{STREAM_LABELS[streamState]}</dd>
        </div>
        <div>
          <dt>Last backend update</dt>
          <dd data-testid="last-backend-update">
            {formatDateTime(snapshot?.last_market_update ?? null)}
          </dd>
        </div>
        <div>
          <dt>Last frame received</dt>
          <dd>{formatDateTime(lastMessageAt)}</dd>
        </div>
        <div>
          <dt>Backend uptime</dt>
          <dd>{health ? `${Math.round(health.uptime_seconds)}s` : '—'}</dd>
        </div>
        <div>
          <dt>Snapshot sequence</dt>
          <dd>{snapshot?.sequence ?? '—'}</dd>
        </div>
        <div>
          <dt>Persistence</dt>
          <dd>
            {events === null
              ? '—'
              : events.enabled
                ? `${events.total_events} events · ${events.total_snapshots} snapshots`
                : 'disabled'}
          </dd>
        </div>
      </dl>

      <div className="alert alert-danger" data-testid="trading-disabled">
        <strong>Trading execution is disabled.</strong> This build is read-only: the strategy
        monitors and confirms setups, but no order can be placed, modified or closed.
      </div>

      {streamNotice ? (
        <p className="alert alert-error" data-testid="ws-notice">
          {streamNotice}
        </p>
      ) : null}

      <div className="errors">
        <h3>Recent connection errors</h3>
        {recentErrors.length === 0 ? (
          <p className="empty" data-testid="no-connection-errors">
            No connection errors recorded.
          </p>
        ) : (
          <ul data-testid="connection-errors">
            {recentErrors.map((event) => (
              <li key={`${event.timestamp}-${event.state}`}>
                <span className="error-time">{formatDateTime(event.timestamp)}</span>
                <span className="error-state">{event.state}</span>
                <span className="error-message">{event.error}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
