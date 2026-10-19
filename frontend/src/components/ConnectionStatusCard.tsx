import {
  describeOverallState,
  stateBadgeClass,
  type OverallState,
} from '../services/dashboardState';
import { formatDateTime, formatDuration, formatTime } from '../services/format';
import type { HealthResponse, MarketSnapshot } from '../types/market';

interface ConnectionStatusCardProps {
  state: OverallState;
  snapshot: MarketSnapshot | null;
  health: HealthResponse | null;
  streamNotice: string | null;
}

/**
 * Backend / terminal / symbol / freshness status.
 *
 * The badge colour is driven by `state`, which the shared derivation only
 * reports as `live` when the backend is genuinely streaming fresh market data.
 * A connected terminal with a silent feed therefore shows as stale, never as
 * green.
 */
export function ConnectionStatusCard({
  state,
  snapshot,
  health,
  streamNotice,
}: ConnectionStatusCardProps) {
  const descriptor = describeOverallState(state, snapshot);
  const connection = snapshot?.connection ?? null;
  const symbol = snapshot?.symbol ?? null;

  const accountType = connection?.account_type ?? 'unknown';
  const accountLabel =
    accountType === 'demo' ? 'Demo account' : accountType === 'live' ? 'LIVE account' : 'Unclassified';

  return (
    <section className="card" aria-labelledby="connection-heading">
      <header className="card-header">
        <h2 id="connection-heading">Connection</h2>
        <span className={stateBadgeClass(state)} data-testid="overall-badge">
          {descriptor.label}
        </span>
      </header>

      <p className="card-detail" data-testid="overall-detail">
        {descriptor.detail}
      </p>

      <dl className="kv">
        <div>
          <dt>Backend</dt>
          <dd data-testid="backend-status">
            {health ? `online · v${health.version} (${health.environment})` : 'unreachable'}
          </dd>
        </div>

        <div>
          <dt>MT5 terminal</dt>
          <dd data-testid="terminal-status">
            {connection
              ? connection.mt5_initialized && connection.terminal_connected
                ? `connected · ${connection.terminal_company ?? 'unknown company'}`
                : `not connected · ${connection.state}`
              : 'unknown'}
          </dd>
        </div>

        <div>
          <dt>Trading server</dt>
          <dd>{connection?.trading_server ?? '—'}</dd>
        </div>

        <div>
          <dt>Account</dt>
          <dd>
            {connection?.account_login_masked ?? '—'}
            {connection?.account_currency ? ` · ${connection.account_currency}` : ''}
            {` · ${accountLabel}`}
          </dd>
        </div>

        <div>
          <dt>Symbol</dt>
          <dd data-testid="symbol-status">
            {symbol?.resolved ?? symbol?.requested ?? '—'}
            {symbol?.resolved && symbol.resolved !== symbol.requested
              ? ` (requested ${symbol.requested})`
              : ''}
          </dd>
        </div>

        <div>
          <dt>Last tick</dt>
          <dd data-testid="last-tick">{formatTime(snapshot?.quote?.tick_time_utc ?? null)}</dd>
        </div>

        <div>
          <dt>Data age</dt>
          <dd data-testid="data-age">{formatDuration(snapshot?.quote_age_seconds ?? null)}</dd>
        </div>

        <div>
          <dt>Last backend update</dt>
          <dd>{formatDateTime(snapshot?.last_market_update ?? health?.timestamp ?? null)}</dd>
        </div>

        <div>
          <dt>Broker / UTC offset</dt>
          <dd>{formatOffset(connection?.server_time_offset_seconds ?? null)}</dd>
        </div>
      </dl>

      {symbol?.requires_configuration ? (
        <p className="alert alert-warning" data-testid="symbol-ambiguity">
          Multiple matching symbols found ({symbol.candidates.join(', ')}). Set{' '}
          <code>MT5_SYMBOL</code> to the exact name in <code>backend/.env</code>.
        </p>
      ) : null}

      {connection?.last_connection_error ? (
        <p className="alert alert-error" data-testid="connection-error">
          {connection.last_connection_error}
        </p>
      ) : null}

      {streamNotice ? (
        <p className="alert alert-error" data-testid="stream-notice">
          {streamNotice}
        </p>
      ) : null}
    </section>
  );
}

function formatOffset(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) {
    return 'not measured yet';
  }
  const sign = seconds >= 0 ? '+' : '-';
  const absolute = Math.abs(seconds);
  const hours = Math.floor(absolute / 3_600);
  const minutes = Math.floor((absolute % 3_600) / 60);
  const rest = absolute % 60;
  return `UTC${sign}${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(
    rest,
  ).padStart(2, '0')}`;
}
