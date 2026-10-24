import type { PerformanceTrade } from '../types/market';
import { formatAmount, formatDateTime, formatSignedAmount, pnlToneClass } from '../services/format';
import { StateBlock } from './terminal/ui';

interface TradesForDayPanelProps {
  trades: PerformanceTrade[];
  /** The selected reporting day (YYYY-MM-DD), if any. */
  day: string | null;
  loading: boolean;
  error: string | null;
  timezone: string | null;
}

/**
 * The completed trades behind one selected day: the full position lifecycle
 * aggregated by the backend's accounting rules (multiple fills and partial
 * closes are one trade). Unclosed positions never appear here - floating
 * results live in the summary cards.
 */
export function TradesForDayPanel({ trades, day, loading, error, timezone }: TradesForDayPanelProps) {
  const dayTrades = day
    ? trades.filter((trade) => trade.close_day === day)
    : [];

  return (
    <section className="card" aria-labelledby="trades-day-heading">
      <header className="card-header">
        <h2 id="trades-day-heading">Trades on a day</h2>
        <span className="history-count" data-testid="trades-day-label">
          {day ? day : 'select a day in the daily table'}
          {timezone ? ` · ${timezone}` : ''}
        </span>
      </header>

      {error && trades.length === 0 ? (
        <p className="alert alert-warning" data-testid="trades-day-error">
          Trade details are temporarily unavailable: {error}
        </p>
      ) : null}

      {!day ? (
        <StateBlock
          title="Pick a day to inspect its trades"
          detail="Select a date row in the Daily P&L table to see the completed trades behind that day's result."
          testId="trades-day-no-selection"
        />
      ) : loading && trades.length === 0 ? (
        <StateBlock title="Loading trade details…" testId="trades-day-loading" />
      ) : dayTrades.length === 0 ? (
        <StateBlock
          title={`No completed trades on ${day}`}
          detail="No closed position was attributed to this day for the current filters."
          testId="trades-day-empty"
        />
      ) : (
        <div className="table-scroll" data-testid="trades-day-table">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Position</th>
                <th scope="col">Symbol</th>
                <th scope="col">Dir</th>
                <th scope="col" className="num">Volume</th>
                <th scope="col">Entry (IST)</th>
                <th scope="col">Exit (IST)</th>
                <th scope="col" className="num">Entry px</th>
                <th scope="col" className="num">Exit px</th>
                <th scope="col" className="num">Gross</th>
                <th scope="col" className="num">Comm</th>
                <th scope="col" className="num">Swap</th>
                <th scope="col" className="num">Fee</th>
                <th scope="col" className="num">Net</th>
                <th scope="col">Deals</th>
                <th scope="col" className="num">Magic</th>
              </tr>
            </thead>
            <tbody>
              {dayTrades.map((trade) => (
                <tr key={trade.position_id}>
                  <td className="mono">#{trade.position_id}</td>
                  <td>{trade.symbol ?? '—'}</td>
                  <td>{trade.direction ?? '—'}</td>
                  <td className="num">{formatAmount(trade.closed_volume)}</td>
                  <td>{formatDateTime(trade.entry_time)}</td>
                  <td>{formatDateTime(trade.exit_time)}</td>
                  <td className="num">{formatAmount(trade.entry_price)}</td>
                  <td className="num">{formatAmount(trade.exit_price)}</td>
                  <td className={`num ${pnlToneClass(trade.gross_pnl)}`}>
                    {formatSignedAmount(trade.gross_pnl)}
                  </td>
                  <td className="num">{formatAmount(trade.costs.commission)}</td>
                  <td className="num">{formatAmount(trade.costs.swap)}</td>
                  <td className="num">{formatAmount(trade.costs.fee)}</td>
                  <td className={`num ${pnlToneClass(trade.net_pnl)}`}>
                    {formatSignedAmount(trade.net_pnl)}
                  </td>
                  <td className="mono" title={trade.order_tickets.join(', ')}>
                    {trade.deal_tickets.join(', ')}
                  </td>
                  <td className="num">{trade.magic ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
