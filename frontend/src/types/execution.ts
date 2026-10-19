/**
 * Types for the Phase 4 demo-execution subsystem (read-only dash integration).
 *
 * These mirror the Pydantic schemas in `app/schemas/execution.py`. They describe
 * authorization posture, risk limits and the execution record only - no order
 * parameters, no live trading. The dashboard consumes these via
 * GET /api/execution/* and never submits an order.
 */

/** Current authorization posture of the demo-execution subsystem. */
export interface ExecutionStatusOut {
  mode: 'disabled' | 'verifying_account' | 'demo_verified' | 'armed' | 'blocked' | 'error';
  configured: boolean;
  armed: boolean;
  demo_verified: boolean;
  account_type: string | null;
  account_login_masked: string | null;
  account_server: string | null;
  account_currency: string | null;
  reasons: string[];
  last_verified_at: string | null;
  armed_at: string | null;
  last_error: string | null;
  daily_lockout: string | null;
  drawdown_lockout: string | null;
  consecutive_losses: number;
  unresolved_executions: number;
  last_reconciled_at: string | null;
  total_executions: number;
  open_bot_positions: number;
  persistence_available: boolean;
  signal_source: 'live_strategy';
  trading_enabled: boolean;
  live_trading_supported: boolean;
  timestamp: string;
}

export const EXECUTION_MODE_LABELS: Record<ExecutionStatusOut['mode'], string> = {
  disabled: 'Disabled',
  verifying_account: 'Verifying account',
  demo_verified: 'Demo verified',
  armed: 'Armed (demo)',
  blocked: 'Blocked',
  error: 'Error',
};

export const EXECUTION_MODE_BADGES: Record<ExecutionStatusOut['mode'], string> = {
  disabled: 'badge badge-unknown',
  verifying_account: 'badge badge-loading',
  demo_verified: 'badge badge-connected',
  armed: 'badge badge-live',
  blocked: 'badge badge-error',
  error: 'badge badge-error',
};

/** Current risk limits and their live consumption. */
export interface RiskStatusOut {
  limits: Record<string, unknown>;
  risk_date: string | null;
  baseline_equity: number | null;
  current_equity: number | null;
  daily_loss: number | null;
  daily_loss_limit: number | null;
  high_water_equity: number | null;
  drawdown: number | null;
  drawdown_limit: number | null;
  aggregate_risk: number | null;
  aggregate_risk_limit: number | null;
  open_bot_positions: number;
  max_open_positions: number;
  bot_positions_missing_stop: number;
  external_positions: number;
  pending_bot_orders: number;
  exposure_unresolved: boolean;
  lockout_reason: string | null;
  consecutive_losses: number;
  timestamp: string;
}

/**
 * One durable execution record (audit view). The Phase 4 backend returns an
 * empty, append-only history; the dashboard reports that honestly rather than
 * inventing fills.
 */
export interface ExecutionRecordOut {
  id: string;
  setup_id: string;
  symbol: string;
  timeframe: string;
  direction: string;
  state: string;
  stage: string | null;
  fill_price: number | null;
  error_code: string | null;
  error_message: string | null;
  reconciliation: string | null;
  created_at: string;
  updated_at: string;
}

export interface ExecutionHistoryOut {
  total: number;
  unresolved: number;
  executions: ExecutionRecordOut[];
}

export function riskStatusIsInBreach(risk: RiskStatusOut | null): boolean {
  if (risk === null) {
    return false;
  }
  if (risk.lockout_reason) {
    return true;
  }
  const dailyBreach =
    risk.daily_loss !== null &&
    risk.daily_loss_limit !== null &&
    risk.daily_loss >= risk.daily_loss_limit;
  const ddBreach =
    risk.drawdown !== null &&
    risk.drawdown_limit !== null &&
    risk.drawdown_limit > 0 &&
    risk.drawdown >= risk.drawdown_limit;
  return dailyBreach || ddBreach;
}

/** Money values are never 0 when they could not be computed. */
export function formatMaybeNumber(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '\u2014';
}

export function formatMaybeCurrency(value: number | null | undefined, currency: string | null): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '\u2014';
  }
  return `${currency ?? 'USD'} ${value.toFixed(2)}`;
}

export function formatMaybePrice(value: number | null | undefined): string {
  return formatMaybeNumber(value);
}