import type { AutoTradingStatus } from '../types/market';
import { formatDateTime } from '../services/format';
import { Pill, type PillTone } from './terminal/ui';
import { ValueOrUnavailable } from './ValueOrUnavailable';

interface AutoTradingPanelProps {
  status: AutoTradingStatus | null;
  /** Request/transport error from polling or the last Start/Stop call. */
  error: string | null;
  busy: boolean;
  onStart: () => void;
  onStop: () => void;
}

const WORKER_TONE: Record<string, PillTone> = {
  RUNNING: 'positive',
  STARTING: 'warning',
  STOPPING: 'warning',
  STOPPED: 'neutral',
  ERROR: 'negative',
};

/**
 * The auto-trading control center: worker state, the existing Start/Stop
 * controls, and the worker's own execution feedback.
 *
 * Behaviour is unchanged from the previous build: Start and Stop call exactly
 * the same endpoints through the lifted hook, never fire while a request is in
 * flight, never start on page load, and the status pill always shows what the
 * backend last reported - never an optimistic assumption.
 */
export function AutoTradingPanel({ status, error, busy, onStart, onStop }: AutoTradingPanelProps) {
  const currentStatus = status?.status ?? 'STOPPED';
  const canStart = currentStatus === 'STOPPED' || currentStatus === 'ERROR';
  const canStop =
    currentStatus === 'RUNNING' || currentStatus === 'STARTING' || currentStatus === 'STOPPING';

  return (
    <section className="card control-card" aria-labelledby="auto-trading-heading">
      <header className="card-header">
        <h2 id="auto-trading-heading">Auto trading</h2>
        <Pill
          tone={WORKER_TONE[currentStatus] ?? 'neutral'}
          testId="auto-trading-status"
          title="Worker state as last reported by the backend"
        >
          {currentStatus}
        </Pill>
      </header>

      <div className="control-row">
        <button
          type="button"
          className="button button-primary"
          data-testid="start-auto-trading"
          onClick={onStart}
          disabled={busy || !canStart}
        >
          Start Auto Trading
        </button>
        <button
          type="button"
          className="button button-danger"
          data-testid="stop-auto-trading"
          onClick={onStop}
          disabled={busy || !canStop}
        >
          Stop Auto Trading
        </button>
        {busy ? (
          <span className="control-busy" role="status" data-testid="auto-trading-busy">
            working…
          </span>
        ) : null}
      </div>

      {error ? (
        <p className="alert alert-error" data-testid="auto-trading-error">
          {error}
        </p>
      ) : null}

      {status?.last_error ? (
        <p className="alert alert-warning" data-testid="auto-last-error-block">
          <strong>Worker message:</strong>{' '}
          <span data-testid="auto-last-error">{status.last_error}</span>
        </p>
      ) : null}

      <div className="execution-results">
        <div className="execution-result">
          <span className="metric-label">Last entry result</span>
          <p className="execution-result-text" data-testid="auto-last-entry">
            {status?.last_entry_result ?? '—'}
          </p>
        </div>
        <div className="execution-result">
          <span className="metric-label">Last exit result</span>
          <p className="execution-result-text" data-testid="auto-last-exit">
            {status?.last_exit_result ?? '—'}
          </p>
        </div>
      </div>

      <dl className="kv kv-compact">
        <div>
          <dt>Symbol / timeframe</dt>
          <dd>
            <span data-testid="auto-symbol">{status?.symbol ?? '—'}</span>
            {' · '}
            <span data-testid="auto-timeframe">{status?.timeframe ?? 'M1'}</span>
          </dd>
        </div>
        <div>
          <dt>Position</dt>
          <dd>
            <span data-testid="auto-position-status">{status?.position_status ?? 'none'}</span>
            {status?.position_ticket != null ? (
              <>
                {' · '}
                <span data-testid="auto-position-ticket">#{status.position_ticket}</span>
              </>
            ) : null}
          </dd>
        </div>
        <div>
          <dt>Entry price</dt>
          <dd data-testid="auto-entry-price">
            <ValueOrUnavailable
              value={formatLevel(status?.entry_price)}
              raw={status?.entry_price ?? null}
            />
          </dd>
        </div>
        <div>
          <dt>Entry time</dt>
          <dd data-testid="auto-entry-time">{formatDateTime(status?.entry_time ?? null)}</dd>
        </div>
        <div>
          <dt>Current P/L</dt>
          <dd data-testid="auto-profit">
            <ValueOrUnavailable
              value={formatSigned(status?.current_profit ?? null)}
              raw={status?.current_profit ?? null}
            />
          </dd>
        </div>
        <div>
          <dt>Next cycle</dt>
          <dd data-testid="auto-next-cycle">{formatDateTime(status?.next_cycle ?? null)}</dd>
        </div>
        <div>
          <dt>Completed cycles</dt>
          <dd data-testid="auto-completed-cycles">{status?.completed_cycles ?? 0}</dd>
        </div>
        <div>
          <dt>Successful entries</dt>
          <dd data-testid="auto-successful-entries">{status?.successful_entries ?? 0}</dd>
        </div>
        <div>
          <dt>Failed entries</dt>
          <dd data-testid="auto-failed-entries">{status?.failed_entries ?? 0}</dd>
        </div>
        <div>
          <dt>Failed exits</dt>
          <dd data-testid="auto-failed-exits">{status?.failed_exits ?? 0}</dd>
        </div>
        <div>
          <dt>Session / magic</dt>
          <dd>
            {status?.session_id ?? '—'} · {status?.magic_number ?? '—'}
          </dd>
        </div>
        <div>
          <dt>Cycle ID</dt>
          <dd>{status?.cycle_id ?? '—'}</dd>
        </div>
      </dl>
    </section>
  );
}

function formatLevel(value: number | null | undefined): string | null {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : null;
}

function formatSigned(value: number | null): string | null {
  if (value === null || !Number.isFinite(value)) {
    return null;
  }
  const fixed = Math.abs(value).toFixed(2);
  return value > 0 ? `+${fixed}` : value < 0 ? `-${fixed}` : fixed;
}
