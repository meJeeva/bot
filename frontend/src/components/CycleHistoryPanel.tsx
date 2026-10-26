import type { AutoTradingHistoryItem } from '../types/market';
import { formatDateTime, isUsableNumber } from '../services/format';
import { StateBlock } from './terminal/ui';

interface CycleHistoryPanelProps {
  items: AutoTradingHistoryItem[];
  error: string | null;
  loaded: boolean;
}

const MAX_ROWS = 25;

/**
 * Completed (or attempted) cycles from `GET /api/auto-trading/history`.
 *
 * Client-side only: newest first, capped rows, no aggregation. The panel never
 * computes win rates or statistics the backend does not publish, and shows an
 * explicit empty state when the backend reports no history.
 */
export function CycleHistoryPanel({ items, error, loaded }: CycleHistoryPanelProps) {
  const ordered = [...items].sort((a, b) => timestampOf(b) - timestampOf(a));
  const visible = ordered.slice(0, MAX_ROWS);

  return (
    <section className="card" aria-labelledby="history-heading">
      <header className="card-header">
        <h2 id="history-heading">Cycle history</h2>
        {ordered.length > 0 ? (
          <span className="history-count" data-testid="history-count">
            showing {visible.length} of {ordered.length}
          </span>
        ) : null}
      </header>

      {error ? (
        <p className="alert alert-warning" data-testid="history-error">
          History is temporarily unavailable: {error}
        </p>
      ) : null}

      {!loaded && !error ? (
        <StateBlock title="Loading cycle history…" testId="history-loading" />
      ) : loaded && ordered.length === 0 && !error ? (
        <StateBlock
          title="No cycle history yet"
          detail="The backend has not recorded any completed cycles. Cycles appear here after the strategy completes them."
          testId="history-empty"
        />
      ) : visible.length > 0 ? (
        <div className="table-scroll" data-testid="history-table">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Cycle</th>
                <th scope="col">Entry (IST)</th>
                <th scope="col">Exit (IST)</th>
                <th scope="col" className="num">Entry</th>
                <th scope="col" className="num">Exit</th>
                <th scope="col" className="num">Volume</th>
                <th scope="col" className="num">Profit</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((item) => (
                <tr key={item.cycle_id} title={item.error ?? undefined}>
                  <td className="mono" data-testid="history-cycle-id">{item.cycle_id}</td>
                  <td>{formatDateTime(item.entry_time)}</td>
                  <td>{formatDateTime(item.exit_time)}</td>
                  <td className="num">{formatNumber(item.entry_price)}</td>
                  <td className="num">{formatNumber(item.exit_price)}</td>
                  <td className="num">{formatNumber(item.volume)}</td>
                  <td className={`num ${profitClass(item.profit)}`}>
                    {formatProfit(item.profit)}
                  </td>
                  <td>
                    <span className={`history-status history-${statusKey(item.status)}`}>
                      {item.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

function timestampOf(item: AutoTradingHistoryItem): number {
  const raw = item.exit_time ?? item.entry_time;
  if (!raw) {
    return 0;
  }
  const parsed = Date.parse(raw);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function formatNumber(value: number | null): string {
  if (!isUsableNumber(value)) {
    return '—';
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

function formatProfit(value: number | null): string {
  if (!isUsableNumber(value)) {
    return '—';
  }
  const fixed = Math.abs(value).toFixed(2);
  return value > 0 ? `+${fixed}` : value < 0 ? `-${fixed}` : fixed;
}

function profitClass(value: number | null): string {
  if (!isUsableNumber(value) || value === 0) {
    return '';
  }
  return value > 0 ? 'text-green' : 'text-red';
}

function statusKey(status: string): string {
  return status.toLowerCase().replace(/[^a-z0-9]+/g, '-');
}
