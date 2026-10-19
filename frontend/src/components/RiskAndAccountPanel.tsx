import type { RiskStatusOut } from '../types/execution';

import { riskStatusIsInBreach } from '../types/execution';

export interface RiskAndAccountPanelProps {
  risk: RiskStatusOut | null;
}

/**
 * Phase 4 — risk and account panel.
 *
 * Shows backend risk limits and consumption (daily loss, drawdown, exposure)
 * plus available account information from MT5 status.
 */
function numberOrDash(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '\u2014';
}

function integerOrDash(value: number | null | undefined): string {
  return Number.isInteger(value) ? String(value) : '\u2014';
}

/**
 * Phase 4 — risk and account panel.
 *
 * Shows backend risk limits and consumption (daily loss, drawdown, exposure)
 * plus available account information from MT5 status.
 */
export function RiskAndAccountPanel({ risk }: RiskAndAccountPanelProps) {
  const riskBreach = risk ? riskStatusIsInBreach(risk) : false;

  const dailyLoss = risk?.daily_loss;
  const dailyLossLimit = risk?.daily_loss_limit;
  const drawdown = risk?.drawdown;
  const drawdownLimit = risk?.drawdown_limit;
  const lockoutReason = risk?.lockout_reason;

  return (
    <section className="card" aria-labelledby="risk-heading">
      <header className="card-header">
        <h2 id="risk-heading">Risk & account</h2>
        <span className={riskBreach ? 'badge badge-error' : 'badge badge-connected'}>
          {riskBreach ? 'Risk breach' : 'Within limits'}
        </span>
      </header>

      <dl className="kv kv-compact">
        <div>
          <dt>Daily loss</dt>
          <dd data-testid="risk-daily-loss">
            {typeof dailyLoss === 'number' && Number.isFinite(dailyLoss) &&
            typeof dailyLossLimit === 'number' && Number.isFinite(dailyLossLimit)
              ? `${dailyLoss.toFixed(2)} / ${dailyLossLimit.toFixed(2)}`
              : '\u2014'}
          </dd>
        </div>

        <div>
          <dt>Daily limit</dt>
          <dd data-testid="risk-daily-limit">{numberOrDash(dailyLossLimit)}</dd>
        </div>

        <div>
          <dt>Drawdown</dt>
          <dd data-testid="risk-drawdown">
            {typeof drawdown === 'number' && Number.isFinite(drawdown) &&
            typeof drawdownLimit === 'number' && Number.isFinite(drawdownLimit) && drawdownLimit > 0 &&
            drawdown >= drawdownLimit
              ? `${drawdown.toFixed(2)} / ${drawdownLimit.toFixed(2)}`
              : '\u2014'}
          </dd>
        </div>

        <div>
          <dt>Drawdown limit</dt>
          <dd data-testid="risk-drawdown-limit">
            {typeof drawdownLimit === 'number' && Number.isFinite(drawdownLimit) && drawdownLimit > 0
              ? drawdownLimit.toFixed(2)
              : '\u2014'}
          </dd>
        </div>

        <div>
          <dt>Open positions</dt>
          <dd data-testid="risk-open-positions">
            {integerOrDash(risk?.open_bot_positions)}
          </dd>
        </div>

        <div>
          <dt>Pending orders</dt>
          <dd data-testid="risk-pending-orders">
            {integerOrDash(risk?.pending_bot_orders)}
          </dd>
        </div>
      </dl>

      {lockoutReason && (
        <p className="alert alert-error" data-testid="risk-lockout">
          Locked out: {lockoutReason}
        </p>
      )}
    </section>
  );
}