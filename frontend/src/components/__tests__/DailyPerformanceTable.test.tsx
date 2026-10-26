import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import {
  makeDailyPerformanceItem,
  makeDailyPerformanceResponse,
} from '../../test/fixtures';
import { DailyPerformanceTable } from '../DailyPerformanceTable';

function baseProps(overrides: Partial<Parameters<typeof DailyPerformanceTable>[0]> = {}) {
  return {
    daily: makeDailyPerformanceResponse([
      makeDailyPerformanceItem({ date: '2026-10-23', net_pnl: 2.65, win_rate: 0.5 }),
      makeDailyPerformanceItem({
        date: '2026-10-22',
        net_pnl: -1.35,
        wins: 0,
        losses: 1,
        closed_trades: 1,
        win_rate: 0,
      }),
    ]),
    loading: false,
    error: null,
    selectedDay: null,
    onSelectDay: vi.fn(),
    ...overrides,
  };
}

describe('DailyPerformanceTable', () => {
  it('renders one row per reporting day with signed, toned amounts', () => {
    render(<DailyPerformanceTable {...baseProps()} />);

    expect(screen.getByTestId('daily-row-2026-10-23')).toHaveTextContent('+2.65');
    expect(screen.getByTestId('daily-row-2026-10-22')).toHaveTextContent('-1.35');
    // Wins and losses are counts, never color-only.
    expect(screen.getByTestId('daily-row-2026-10-22')).toHaveTextContent('0');
    expect(screen.getByTestId('daily-row-2026-10-22')).toHaveTextContent('1');
  });

  it('shows the period totals underneath the days', () => {
    render(<DailyPerformanceTable {...baseProps()} />);

    const totals = screen.getByTestId('daily-totals');
    expect(totals).toHaveTextContent('Totals');
    expect(totals).toHaveTextContent('3');
    expect(totals).toHaveTextContent('+1.30');
  });

  it('labels the reporting timezone and account currency', () => {
    render(<DailyPerformanceTable {...baseProps()} />);

    expect(screen.getByTestId('daily-perf-range')).toHaveTextContent('Asia/Kolkata');
    expect(screen.getByTestId('daily-perf-range')).toHaveTextContent('USD');
  });

  it('sorts by date in both directions without refetching', () => {
    render(<DailyPerformanceTable {...baseProps()} />);

    fireEvent.click(screen.getByTestId('daily-sort'));
    const rowsDesc = screen.getAllByTestId(/daily-row-\d{4}-\d{2}-\d{2}/);
    expect(rowsDesc[0]).toHaveTextContent('2026-10-23');

    fireEvent.click(screen.getByTestId('daily-sort'));
    const rowsAsc = screen.getAllByTestId(/daily-row-\d{4}-\d{2}-\d{2}/);
    expect(rowsAsc[0]).toHaveTextContent('2026-10-22');
  });

  it('reports the selected day to the trade drill-down', () => {
    const onSelectDay = vi.fn();
    render(<DailyPerformanceTable {...baseProps({ onSelectDay, selectedDay: '2026-10-23' })} />);

    fireEvent.click(screen.getByTestId('daily-select-2026-10-22'));
    expect(onSelectDay).toHaveBeenCalledWith('2026-10-22');
    // The selected row is highlighted, not silently dropped.
    expect(screen.getByTestId('daily-row-2026-10-23')).toHaveClass('row-selected');
  });

  it('separates the unavailable, loading and no-data states', () => {
    const first = render(
      <DailyPerformanceTable
        {...baseProps({
          daily: makeDailyPerformanceResponse([], {
            data_available: false,
            error: 'history_deals_get returned None (API error)',
          }),
        })}
      />,
    );
    expect(screen.getByTestId('daily-perf-unavailable')).toHaveTextContent(
      'Data temporarily unavailable',
    );
    first.unmount();

    render(<DailyPerformanceTable {...baseProps({ daily: null, loading: true })} />);
    expect(screen.getByTestId('daily-perf-loading')).toBeInTheDocument();
  });

  it('explains a successful but empty range', () => {
    render(<DailyPerformanceTable {...baseProps({ daily: makeDailyPerformanceResponse([]) })} />);

    expect(screen.getByTestId('daily-perf-no-days')).toBeInTheDocument();
    expect(screen.getByTestId('daily-perf-no-days')).toHaveTextContent('successful, empty history');
  });
});
