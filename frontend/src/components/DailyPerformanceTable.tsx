import { useState } from 'react';

import type { DailyPerformanceItem, DailyPerformanceResponse } from '../types/market';
import {
  formatAmount,
  formatRatio,
  formatSignedAmount,
  pnlToneClass,
} from '../services/format';
import { StateBlock } from './terminal/ui';

interface DailyPerformanceTableProps {
  daily: DailyPerformanceResponse | null;
  loading: boolean;
  error: string | null;
  selectedDay: string | null;
  onSelectDay: (day: string) => void;
}

type SortDirection = 'asc' | 'desc';

/**
 * One row per reporting day, attributed by each trade's close time in the
 * reporting timezone, with the period totals underneath. Selecting a day
 * shows the trades that produced that day's result; sorting is client-side
 * over the already-loaded rows and never refetches.
 */
export function DailyPerformanceTable({
  daily,
  loading,
  error,
  selectedDay,
  onSelectDay,
}: DailyPerformanceTableProps) {
  const [sortDir, setSortDir] = useState<SortDirection>('asc');

  if (error && daily === null) {
    return (
      <section className="card" aria-labelledby="daily-perf-heading">
        <header className="card-header">
          <h2 id="daily-perf-heading">Daily P&amp;L</h2>
        </header>
        <StateBlock
          title="Daily performance is temporarily unavailable"
          detail={error}
          tone="error"
          testId="daily-perf-error"
        />
      </section>
    );
  }

  if (loading && daily === null) {
    return (
      <section className="card" aria-labelledby="daily-perf-heading">
        <header className="card-header">
          <h2 id="daily-perf-heading">Daily P&amp;L</h2>
        </header>
        <StateBlock title="Loading daily performance…" testId="daily-perf-loading" />
      </section>
    );
  }

  if (daily === null) {
    return (
      <section className="card" aria-labelledby="daily-perf-heading">
        <header className="card-header">
          <h2 id="daily-perf-heading">Daily P&amp;L</h2>
        </header>
        <StateBlock title="No daily data" testId="daily-perf-empty" />
      </section>
    );
  }

  const days = sortedDays(daily.days, sortDir);
  const totals = daily.totals;

  return (
    <section className="card" aria-labelledby="daily-perf-heading">
      <header className="card-header">
        <h2 id="daily-perf-heading">Daily P&amp;L</h2>
        <span className="history-count" data-testid="daily-perf-range">
          {daily.range_start} → {daily.range_end} · {daily.reporting_timezone}
          {daily.account_currency ? ` · ${daily.account_currency}` : ''}
        </span>
      </header>

      {daily.data_available === false && daily.error ? (
        <p className="alert alert-warning" data-testid="daily-perf-unavailable">
          Data temporarily unavailable: {daily.error}
        </p>
      ) : null}

      {days.length === 0 ? (
        <StateBlock
          title="No trading days in this range"
          detail="The backend returned a successful, empty history for this range and filter set."
          testId="daily-perf-no-days"
        />
      ) : (
        <div className="table-scroll" data-testid="daily-perf-table">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">
                  <button
                    type="button"
                    className="th-sort"
                    onClick={() => setSortDir((current) => (current === 'asc' ? 'desc' : 'asc'))}
                    data-testid="daily-sort"
                  >
                    Date ({sortDir === 'asc' ? 'oldest first' : 'newest first'})
                  </button>
                </th>
                <th scope="col" className="num">Closed trades</th>
                <th scope="col" className="num">Wins</th>
                <th scope="col" className="num">Losses</th>
                <th scope="col" className="num">Gross P&amp;L</th>
                <th scope="col" className="num">Costs</th>
                <th scope="col" className="num">Net P&amp;L</th>
                <th scope="col" className="num">Win rate</th>
              </tr>
            </thead>
            <tbody>
              {days.map((day) => (
                <tr
                  key={day.date}
                  className={day.date === selectedDay ? 'row-selected' : ''}
                  data-testid={`daily-row-${day.date}`}
                >
                  <td>
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => onSelectDay(day.date)}
                      data-testid={`daily-select-${day.date}`}
                    >
                      {day.date}
                    </button>
                  </td>
                  <td className="num">{day.closed_trades}</td>
                  <td className="num text-green">{day.wins}</td>
                  <td className="num text-red">{day.losses}</td>
                  <td className={`num ${pnlToneClass(day.gross_pnl)}`}>
                    {formatSignedAmount(day.gross_pnl)}
                  </td>
                  <td className="num">{formatAmount(day.costs.total)}</td>
                  <td className={`num ${pnlToneClass(day.net_pnl)}`}>
                    {formatSignedAmount(day.net_pnl)}
                  </td>
                  <td className="num">{formatRatio(day.win_rate)}</td>
                </tr>
              ))}
            </tbody>
            {totals ? (
              <tfoot>
                <tr data-testid="daily-totals">
                  <td>Totals</td>
                  <td className="num">{totals.closed_trades}</td>
                  <td className="num text-green">{totals.wins}</td>
                  <td className="num text-red">{totals.losses}</td>
                  <td className={`num ${pnlToneClass(totals.gross_pnl)}`}>
                    {formatSignedAmount(totals.gross_pnl)}
                  </td>
                  <td className="num">{formatAmount(totals.costs.total)}</td>
                  <td className={`num ${pnlToneClass(totals.net_pnl)}`}>
                    {formatSignedAmount(totals.net_pnl)}
                  </td>
                  <td className="num">{formatRatio(totals.win_rate)}</td>
                </tr>
              </tfoot>
            ) : null}
          </table>
        </div>
      )}
    </section>
  );
}

function sortedDays(
  days: DailyPerformanceItem[],
  direction: SortDirection,
): DailyPerformanceItem[] {
  const copy = [...days];
  copy.sort((a, b) =>
    direction === 'asc' ? a.date.localeCompare(b.date) : b.date.localeCompare(a.date),
  );
  return copy;
}
