import { formatDateTime } from '../services/format';
import type { ExecutionStatusOut } from '../types/execution';

import { EXECUTION_MODE_BADGES, EXECUTION_MODE_LABELS } from '../types/execution';

export interface ExecutionStatusPanelProps {
  status: ExecutionStatusOut | null;
  onRefresh: () => void;
}

/**
 * Phase 4 — demo execution safety panel.
 *
 * Shows the real backend authorization state from GET /api/execution/status.
 * Execution remains disabled by default. Never automatically arms during
 * initialization or reconnection.
 */
export function ExecutionStatusPanel({ status, onRefresh }: ExecutionStatusPanelProps) {
  if (status === null) {
    return (
      <section className="card" aria-labelledby="execution-heading">
        <header className="card-header">
          <h2 id="execution-heading">Execution status</h2>
        </header>
        <p className="empty" data-testid="execution-none">
          Loading execution status...
        </p>
      </section>
    );
  }

  const mode = status.mode;
  const configured = status.configured;
  const armed = status.armed;
  const demoVerified = status.demo_verified;
  const reasons = status.reasons;
  const lastVerifiedAt = status.last_verified_at;
  const armedAt = status.armed_at;
  const lastError = status.last_error;

  return (
    <section className="card" aria-labelledby="execution-heading">
      <header className="card-header">
        <h2 id="execution-heading">Execution status</h2>
        <span className={
          EXECUTION_MODE_BADGES[mode as keyof typeof EXECUTION_MODE_BADGES]
        } data-testid="execution-mode-badge">
          {EXECUTION_MODE_LABELS[mode]}
        </span>
      </header>

      <dl className="kv kv-compact">
        <div>
          <dt>Mode</dt>
          <dd data-testid="execution-mode">{EXECUTION_MODE_LABELS[mode]}</dd>
        </div>

        <div>
          <dt>Configured</dt>
          <dd data-testid="execution-configured">{configured ? 'Yes' : 'No'}</dd>
        </div>

        <div>
          <dt>Demo verified</dt>
          <dd data-testid="execution-demo-verified">
            {demoVerified ? 'Yes' : 'No'}
          </dd>
        </div>

        <div>
          <dt>Armed</dt>
          <dd data-testid="execution-armed">
            {armed ? 'Yes' : 'No'}
          </dd>
        </div>

        <div>
          <dt>Last verified</dt>
          <dd data-testid="execution-last-verified">
            {lastVerifiedAt ? formatDateTime(lastVerifiedAt) : '—'}
          </dd>
        </div>

        <div>
          <dt>Armed at</dt>
          <dd data-testid="execution-armed-at">
            {armedAt ? formatDateTime(armedAt) : '—'}
          </dd>
        </div>

        <div>
          <dt>Unresolved executions</dt>
          <dd data-testid="execution-unresolved">{status.unresolved_executions}</dd>
        </div>

        <div>
          <dt>Last reconciled</dt>
          <dd data-testid="execution-last-reconciled">
            {status.last_reconciled_at ? formatDateTime(status.last_reconciled_at) : '—'}
          </dd>
        </div>
      </dl>

      {reasons.length > 0 ? (
        <p className="alert alert-warning" data-testid="execution-reasons">
          {reasons.join(', ')}
        </p>
      ) : (
        <p className="empty" data-testid="execution-no-reasons">
          No restrictions recorded.
        </p>
      )}

      {lastError ? (
        <p className="alert alert-error" data-testid="execution-last-error">
          {lastError}
        </p>
      ) : null}

      <button
        type="button"
        className="button"
        data-testid="execution-refresh-button"
        onClick={onRefresh}
      >
        Refresh
      </button>
    </section>
  );
}
