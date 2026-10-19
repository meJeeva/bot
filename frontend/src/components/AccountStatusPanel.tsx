import { formatDateTime } from '../services/format';
import type { MarketSnapshot } from '../types/market';
import type { RiskStatusOut } from '../types/execution';
import { formatMaybeCurrency } from '../types/execution';

export interface AccountStatusPanelProps {
  snapshot: MarketSnapshot | null;
  risk: RiskStatusOut | null;
}

/**
 * Account and connection status for the Risk & Execution view.
 *
 * Values come straight from the backend snapshot and risk status. Equity is
 * shown only when the risk engine actually computed it; a missing value stays
 * missing rather than reading as a zero balance.
 */
export function AccountStatusPanel({ snapshot, risk }: AccountStatusPanelProps) {
  const connection = snapshot?.connection ?? null;
  const accountType = connection?.account_type ?? 'unknown';
  const accountLabel =
    accountType === 'demo' ? 'Demo' : accountType === 'live' ? 'LIVE' : 'Unclassified';

  return (
    <section className="card" aria-labelledby="account-heading">
      <header className="card-header">
        <h2 id="account-heading">Account &amp; connection</h2>
        <span className="badge badge-unknown" data-testid="account-type-badge">
          {accountLabel}
        </span>
      </header>

      <dl className="kv kv-compact">
        <div>
          <dt>Account</dt>
          <dd data-testid="account-login">
            {connection?.account_login_masked ?? '—'}
            {connection?.account_currency ? ` · ${connection.account_currency}` : ''}
          </dd>
        </div>
        <div>
          <dt>Trading server</dt>
          <dd data-testid="account-server">{connection?.trading_server ?? '—'}</dd>
        </div>
        <div>
          <dt>Terminal</dt>
          <dd data-testid="account-terminal">
            {connection
              ? connection.terminal_connected
                ? 'connected'
                : `not connected (${connection.state})`
              : 'unknown'}
          </dd>
        </div>
        <div>
          <dt>Current equity</dt>
          <dd data-testid="account-equity">
            {formatMaybeCurrency(risk?.current_equity ?? null, connection?.account_currency ?? null)}
          </dd>
        </div>
        <div>
          <dt>Baseline equity</dt>
          <dd data-testid="account-baseline-equity">
            {formatMaybeCurrency(risk?.baseline_equity ?? null, connection?.account_currency ?? null)}
          </dd>
        </div>
        <div>
          <dt>High-water equity</dt>
          <dd data-testid="account-high-water">
            {formatMaybeCurrency(risk?.high_water_equity ?? null, connection?.account_currency ?? null)}
          </dd>
        </div>
        <div>
          <dt>Last tick</dt>
          <dd>{formatDateTime(snapshot?.quote?.tick_time_utc ?? null)}</dd>
        </div>
        <div>
          <dt>Data status</dt>
          <dd data-testid="account-data-status">{snapshot?.data_status ?? '—'}</dd>
        </div>
      </dl>

      {connection?.account_type === 'live' ? (
        <p className="alert alert-error" data-testid="account-live-warning">
          A live account is connected. Execution is demo-only and remains disabled.
        </p>
      ) : null}
    </section>
  );
}
