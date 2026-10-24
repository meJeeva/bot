import { useState, type ReactNode } from 'react';

import type { PerformanceSummary } from '../types/market';
import {
  formatAmount,
  formatRatio,
  formatSignedAmount,
  pnlToneClass,
} from '../services/format';
import {
  usePerformance,
  type PerformanceFilterState,
  type PresetKey,
} from '../hooks/usePerformance';
import { DailyPerformanceTable } from './DailyPerformanceTable';
import { CumulativePnlChart } from './CumulativePnlChart';
import { TradesForDayPanel } from './TradesForDayPanel';

const PRESET_OPTIONS: Array<{ value: PresetKey; label: string }> = [
  { value: 'd10', label: 'Last 10 days' },
  { value: 'today', label: 'Today' },
  { value: 'yesterday', label: 'Yesterday' },
  { value: 'd7', label: 'Last 7 days' },
  { value: 'd30', label: 'Last 30 days' },
  { value: 'week', label: 'This week' },
  { value: 'month', label: 'This month' },
  { value: 'custom', label: 'Custom range' },
];

/**
 * The P&L summary section: reporting filters, the headline cards, the daily
 * table with its cumulative curve, and the trade-level drill-down.
 *
 * Every figure comes from the backend's read-only performance endpoints,
 * which compute from MT5 deal history. When history cannot be read the cards
 * say "Data temporarily unavailable" - they never fall back to zero.
 */
export function PerformancePanel() {
  const {
    filters,
    setFilters,
    resetFilters,
    today,
    week,
    month,
    rangeSummary,
    daily,
    trades,
    loading,
    error,
    refresh,
  } = usePerformance();
  const [selectedDay, setSelectedDay] = useState<string | null>(null);

  const timezone = rangeSummary?.reporting_timezone ?? daily?.reporting_timezone ?? null;
  const currency = rangeSummary?.account_currency ?? daily?.account_currency ?? null;
  const accountRule = rangeSummary?.accounting_rule ?? null;

  const update = (patch: Partial<PerformanceFilterState>) => {
    setFilters({ ...filters, ...patch });
  };

  const todayCard = today;
  const weekCard = week;
  const monthCard = month;

  return (
    <section className="card performance-card" aria-labelledby="performance-heading">
      <header className="card-header">
        <h2 id="performance-heading">Performance</h2>
        <div className="section-actions">
          {timezone ? (
            <span className="history-count" data-testid="perf-timezone">
              reporting timezone {timezone}
            </span>
          ) : null}
          {currency ? (
            <span className="history-count" data-testid="perf-currency">
              {currency}
            </span>
          ) : null}
          <button
            type="button"
            className="button"
            onClick={refresh}
            data-testid="perf-refresh"
          >
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </header>

      {error ? (
        <p className="alert alert-error" data-testid="perf-error">
          {error}
        </p>
      ) : null}

      <div className="filter-row" data-testid="perf-filters">
        <label className="filter-field">
          <span>Range</span>
          <select
            value={filters.preset}
            onChange={(event) => update({ preset: event.target.value as PresetKey })}
            data-testid="perf-preset"
          >
            {PRESET_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        {filters.preset === 'custom' ? (
          <>
            <label className="filter-field">
              <span>From</span>
              <input
                type="date"
                value={filters.startDate}
                onChange={(event) => update({ startDate: event.target.value })}
                data-testid="perf-start"
              />
            </label>
            <label className="filter-field">
              <span>To</span>
              <input
                type="date"
                value={filters.endDate}
                onChange={(event) => update({ endDate: event.target.value })}
                data-testid="perf-end"
              />
            </label>
          </>
        ) : null}

        <label className="filter-field">
          <span>Symbol</span>
          <input
            type="text"
            placeholder="all symbols"
            value={filters.symbol}
            onChange={(event) => update({ symbol: event.target.value })}
            data-testid="perf-symbol"
          />
        </label>

        <label className="filter-field">
          <span>Direction</span>
          <select
            value={filters.direction}
            onChange={(event) =>
              update({ direction: event.target.value as '' | 'buy' | 'sell' })
            }
            data-testid="perf-direction"
          >
            <option value="">Buy &amp; Sell</option>
            <option value="buy">Buy only</option>
            <option value="sell">Sell only</option>
          </select>
        </label>

        <label className="filter-field">
          <span>Magic</span>
          <input
            type="text"
            inputMode="numeric"
            placeholder="all"
            value={filters.magic}
            onChange={(event) => update({ magic: event.target.value })}
            data-testid="perf-magic"
          />
        </label>

        <button
          type="button"
          className="button"
          onClick={() => {
            resetFilters();
            setSelectedDay(null);
          }}
          data-testid="perf-reset"
        >
          Reset filters
        </button>
      </div>

      <div className="perf-cards" data-testid="perf-cards">
        <NetCard
          label="Today's realized net P&L"
          summary={todayCard}
          testId="perf-today"
        />
        <CountsCard summary={todayCard} testId="perf-today-counts" />
        <NetCard
          label="This week's realized net P&L"
          summary={weekCard}
          testId="perf-week"
        />
        <NetCard
          label="This month's realized net P&L"
          summary={monthCard}
          testId="perf-month"
        />
        <NetCard
          label={
            filters.preset === 'd10'
              ? "Last 10 days' realized net P&L"
              : 'Selected range net P&L'
          }
          summary={rangeSummary}
          testId="perf-range"
          sub={
            rangeSummary
              ? `${rangeSummary.filters?.preset ?? 'custom'}: ${rangeSummary.range_start} → ${rangeSummary.range_end}`
              : undefined
          }
        />
        <Card
          label="Floating P&L (open positions)"
          testId="perf-floating"
          summary={rangeSummary}
          value={
            rangeSummary?.data_available ? (
              <span className={pnlToneClass(rangeSummary.floating.total)}>
                {formatSignedAmount(rangeSummary.floating.total)}
              </span>
            ) : null
          }
          sub={
            rangeSummary?.data_available
              ? `${rangeSummary.floating.open_positions} open position(s) · profit ${formatSignedAmount(
                  rangeSummary.floating.profit,
                )} · swap ${formatSignedAmount(rangeSummary.floating.swap)}`
              : 'separate from realized results'
          }
        />
        <MoneyCard
          label={`Balance${currency ? ` (${currency})` : ''}`}
          summary={rangeSummary}
          value={rangeSummary?.balance ?? null}
          testId="perf-balance"
        />
        <MoneyCard
          label={`Equity${currency ? ` (${currency})` : ''}`}
          summary={rangeSummary}
          value={rangeSummary?.equity ?? null}
          testId="perf-equity"
        />
        <Card
          label="Trading costs (selected range)"
          testId="perf-costs"
          summary={rangeSummary}
          value={
            rangeSummary?.data_available ? (
              <span>{formatSignedAmount(rangeSummary.costs.total)}</span>
            ) : null
          }
          sub={
            rangeSummary?.data_available
              ? `commission ${formatAmount(rangeSummary.costs.commission)} · swap ${formatAmount(
                  rangeSummary.costs.swap,
                )} · fee ${formatAmount(rangeSummary.costs.fee)}`
              : undefined
          }
        />
        <Card
          label="Deposits, withdrawals & other movements"
          testId="perf-cash"
          summary={rangeSummary}
          value={
            rangeSummary?.data_available ? (
              <span>{formatSignedAmount(rangeSummary.cash_movements_total)}</span>
            ) : null
          }
          sub={
            rangeSummary?.data_available
              ? `${rangeSummary.cash_movements.length} non-trading movement(s), excluded from trading P&L`
              : undefined
          }
        />
      </div>

      <div className="performance-lower">
        <CumulativePnlChart
          days={daily?.days ?? []}
          currency={currency}
          timezone={timezone ?? 'reporting timezone unavailable'}
        />
      </div>

      <DailyPerformanceTable
        daily={daily}
        loading={loading}
        error={error}
        selectedDay={selectedDay}
        onSelectDay={setSelectedDay}
      />

      <TradesForDayPanel
        trades={trades?.trades ?? []}
        day={selectedDay}
        loading={loading}
        error={error}
        timezone={timezone}
      />

      {accountRule ? (
        <details className="accounting-rule" data-testid="perf-accounting-rule">
          <summary>How net P&L is calculated</summary>
          <p>{accountRule}</p>
        </details>
      ) : null}
    </section>
  );
}

interface CardProps {
  label: string;
  testId: string;
  summary: PerformanceSummary | null;
  value: ReactNode;
  sub?: string;
}

/**
 * One summary card. `data_available: false` renders the explicit unavailable
 * state with the backend's reason - never a zero, never a stale number
 * presented as current.
 */
function Card({ label, testId, summary, value, sub }: CardProps) {
  const unavailable = summary !== null && summary.data_available === false;
  return (
    <div className={`metric perf-metric${unavailable ? ' perf-unavailable' : ''}`} data-testid={testId}>
      <span className="metric-label">{label}</span>
      <span className="metric-value">
        {summary === null ? '—' : unavailable ? 'Data temporarily unavailable' : value}
      </span>
      <span className="metric-sub" title={unavailable ? (summary?.error ?? '') : undefined}>
        {summary === null
          ? 'loading…'
          : unavailable
            ? (summary.error ?? 'history unavailable')
            : (sub ?? '')}
      </span>
    </div>
  );
}

function NetCard({
  label,
  summary,
  testId,
  sub,
}: {
  label: string;
  summary: PerformanceSummary | null;
  testId: string;
  sub?: string;
}) {
  const detail =
    sub ??
    (summary?.data_available
      ? `${summary.closed_trades} closed · ${summary.wins}W / ${summary.losses}L`
      : undefined);
  return (
    <Card
      label={label}
      testId={testId}
      summary={summary}
      value={
        summary?.data_available ? (
          <span className={pnlToneClass(summary.net_pnl)}>
            {formatSignedAmount(summary.net_pnl)}
            {summary.account_currency ? (
              <span className="value-suffix">{summary.account_currency}</span>
            ) : null}
          </span>
        ) : null
      }
      sub={detail}
    />
  );
}

function CountsCard({
  summary,
  testId,
}: {
  summary: PerformanceSummary | null;
  testId: string;
}) {
  return (
    <Card
      label="Today's closed trades & win rate"
      testId={testId}
      summary={summary}
      value={
        summary?.data_available ? (
          <>
            {summary.closed_trades}
            <span className="value-suffix">
              {formatRatio(summary.win_rate)} win rate
            </span>
          </>
        ) : null
      }
      sub={
        summary?.data_available
          ? `${summary.wins} winning · ${summary.losses} losing`
          : undefined
      }
    />
  );
}

function MoneyCard({
  label,
  summary,
  value,
  testId,
}: {
  label: string;
  summary: PerformanceSummary | null;
  value: number | null;
  testId: string;
}) {
  return (
    <Card
      label={label}
      testId={testId}
      summary={summary}
      value={
        summary?.data_available ? <span>{formatAmount(value)}</span> : null
      }
      sub={summary?.data_available ? 'account level, includes floating result' : undefined}
    />
  );
}
