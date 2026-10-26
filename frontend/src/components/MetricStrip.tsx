import type { AutoTradingStatus } from '../types/market';
import { UNAVAILABLE_GLYPH, isUsableNumber } from '../services/format';
import { ValueOrUnavailable } from './ValueOrUnavailable';

interface MetricStripProps {
  status: AutoTradingStatus | null;
  /** Account currency as reported by the backend, e.g. `USD`. */
  currency: string | null;
  /** Short connectivity word derived from the market snapshot. */
  connectivity: string;
  connectivityHealthy: boolean;
}

/**
 * The compact headline row: account, position, connectivity and worker state.
 *
 * Every value comes from an existing backend field; anything the backend did
 * not supply renders as the unavailable placeholder, never as zero.
 */
export function MetricStrip({
  status,
  currency,
  connectivity,
  connectivityHealthy,
}: MetricStripProps) {
  const positionOpen = (status?.position_ticket ?? null) !== null;
  const positionLabel = status
    ? positionOpen
      ? `#${status.position_ticket}`
      : status.position_status || 'none'
    : UNAVAILABLE_GLYPH;
  const profit = status?.current_profit ?? null;
  const workerStatus = status?.status ?? null;

  return (
    <section className="metric-strip" aria-label="Account and worker summary">
      <div className="metric" data-testid="metric-balance">
        <span className="metric-label">Balance</span>
        <span className="metric-value">
          <ValueOrUnavailable
            value={formatMoney(status?.balance ?? null)}
            raw={status?.balance ?? null}
            suffix={currency ?? undefined}
          />
        </span>
        <span className="metric-sub">account currency {currency ?? UNAVAILABLE_GLYPH}</span>
      </div>

      <div className="metric" data-testid="metric-equity">
        <span className="metric-label">Equity</span>
        <span className="metric-value">
          <ValueOrUnavailable
            value={formatMoney(status?.equity ?? null)}
            raw={status?.equity ?? null}
            suffix={currency ?? undefined}
          />
        </span>
        <span className="metric-sub">incl. floating result</span>
      </div>

      <div className="metric" data-testid="metric-position">
        <span className="metric-label">Position</span>
        <span className={`metric-value${positionOpen ? ' metric-value-accent' : ''}`}>
          {positionLabel}
        </span>
        <span className="metric-sub">
          {positionOpen ? 'open strategy position' : 'no open strategy position'}
        </span>
      </div>

      <div className="metric" data-testid="metric-pnl">
        <span className="metric-label">Floating P&amp;L</span>
        <span className={`metric-value ${pnlClass(profit)}`}>
          {profit === null ? <ValueOrUnavailable value={null} /> : formatSigned(profit)}
          {profit !== null && currency ? (
            <span className="value-suffix">{currency}</span>
          ) : null}
        </span>
        <span className="metric-sub">open position only</span>
      </div>

      <div className="metric" data-testid="metric-connectivity">
        <span className="metric-label">MT5 terminal</span>
        <span className={`metric-value ${connectivityHealthy ? 'text-green' : 'text-amber'}`}>
          {connectivity}
        </span>
        <span className="metric-sub">market data link</span>
      </div>

      <div className="metric" data-testid="metric-worker">
        <span className="metric-label">Auto trading</span>
        <span className={`metric-value ${workerToneClass(workerStatus)}`}>
          {workerStatus ?? UNAVAILABLE_GLYPH}
        </span>
        <span className="metric-sub">strategy worker state</span>
      </div>

      <div className="metric" data-testid="metric-cycles">
        <span className="metric-label">Completed cycles</span>
        <span className="metric-value">
          <ValueOrUnavailable
            value={isUsableNumber(status?.completed_cycles) ? String(status.completed_cycles) : null}
            raw={status?.completed_cycles ?? null}
          />
        </span>
        <span className="metric-sub">
          {isUsableNumber(status?.session_completed_cycles)
            ? `${status.session_completed_cycles} this session`
            : 'session count unavailable'}
        </span>
      </div>
    </section>
  );
}

function formatMoney(value: number | null): string | null {
  if (!isUsableNumber(value)) {
    return null;
  }
  return value.toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatSigned(value: number): string {
  const fixed = Math.abs(value).toFixed(2);
  return value > 0 ? `+${fixed}` : value < 0 ? `-${fixed}` : fixed;
}

function pnlClass(value: number | null): string {
  if (value === null) {
    return '';
  }
  if (value > 0) {
    return 'text-green';
  }
  if (value < 0) {
    return 'text-red';
  }
  return '';
}

function workerToneClass(status: string | null): string {
  switch (status) {
    case 'RUNNING':
      return 'text-green';
    case 'STARTING':
    case 'STOPPING':
      return 'text-amber';
    case 'ERROR':
      return 'text-red';
    default:
      return '';
  }
}
