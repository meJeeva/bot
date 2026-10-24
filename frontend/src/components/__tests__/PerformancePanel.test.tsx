import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  makeDailyPerformanceResponse,
  makePerformanceSummary,
  makePerformanceTrade,
  makePerformanceTradesResponse,
} from '../../test/fixtures';
import { PerformancePanel } from '../PerformancePanel';
import { api } from '../../services/api';

vi.mock('../../services/api', () => ({
  api: {
    performance: {
      summary: vi.fn(),
      daily: vi.fn(),
      trades: vi.fn(),
    },
  },
  describeError: (error: unknown) => String(error),
}));

const mockedApi = vi.mocked(api, { deep: true });

function installHappyPath(): void {
  mockedApi.performance.summary.mockImplementation(async (_query) => makePerformanceSummary());
  mockedApi.performance.daily.mockImplementation(async (_query) => makeDailyPerformanceResponse());
  mockedApi.performance.trades.mockImplementation(async (_query) =>
    makePerformanceTradesResponse(),
  );
}

beforeEach(() => {
  mockedApi.performance.summary.mockReset();
  mockedApi.performance.daily.mockReset();
  mockedApi.performance.trades.mockReset();
  installHappyPath();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('PerformancePanel', () => {
  it('renders the headline cards from server-computed summaries', async () => {
    render(<PerformancePanel />);

    await waitFor(() => {
      expect(screen.getByTestId('perf-today')).toHaveTextContent('+23.15');
    });
    // The dashboard opens on the last 10 days by default.
    expect(screen.getByTestId('perf-preset')).toHaveValue('d10');
    expect(screen.getByTestId('perf-today-counts')).toHaveTextContent('7');
    expect(screen.getByTestId('perf-today-counts')).toHaveTextContent('57.1% win rate');
    expect(screen.getByTestId('perf-week')).toHaveTextContent('+23.15');
    expect(screen.getByTestId('perf-month')).toHaveTextContent('+23.15');
    // Balance and equity are labelled with the account currency elsewhere.
    expect(screen.getByTestId('perf-currency')).toHaveTextContent('USD');
    expect(screen.getByTestId('perf-timezone')).toHaveTextContent('Asia/Kolkata');
  });

  it('keeps floating P&L separate from realized results', async () => {
    render(<PerformancePanel />);

    await waitFor(() => {
      expect(screen.getByTestId('perf-floating')).toHaveTextContent('+12.20');
    });
    expect(screen.getByTestId('perf-floating')).toHaveTextContent('1 open position(s)');
    // The realized net on the same dashboard does not include the floating amount.
    expect(screen.getByTestId('perf-range')).toHaveTextContent('+23.15');
  });

  it('shows trading costs and keeps non-trading cash movements out of them', async () => {
    render(<PerformancePanel />);

    await waitFor(() => {
      expect(screen.getByTestId('perf-costs')).toHaveTextContent('-1.35');
    });
    expect(screen.getByTestId('perf-costs')).toHaveTextContent('commission -1.00');
    expect(screen.getByTestId('perf-cash')).toHaveTextContent('+500.00');
    expect(screen.getByTestId('perf-cash')).toHaveTextContent(
      'excluded from trading P&L',
    );
  });

  it('renders the explicit unavailable state instead of zeros when history fails', async () => {
    mockedApi.performance.summary.mockImplementation(async (_query) =>
      makePerformanceSummary({
        data_available: false,
        error: 'history_deals_get returned None (API error)',
        net_pnl: 0,
        closed_trades: 0,
      }),
    );

    render(<PerformancePanel />);

    await waitFor(() => {
      expect(screen.getAllByText('Data temporarily unavailable').length).toBeGreaterThan(0);
    });
    // No headline card claims a zero profit.
    expect(screen.getByTestId('perf-today')).not.toHaveTextContent('+0.00');
    expect(screen.getByTestId('perf-today')).toHaveTextContent(
      'history_deals_get returned None (API error)',
    );
  });

  it('exposes the range filters and resets them', async () => {
    render(<PerformancePanel />);

    await waitFor(() => {
      expect(screen.getByTestId('perf-preset')).toBeInTheDocument();
    });

    // Symbol and direction apply to any range, including the presets.
    fireEvent.change(screen.getByTestId('perf-symbol'), { target: { value: 'xauusd' } });
    fireEvent.change(screen.getByTestId('perf-direction'), { target: { value: 'sell' } });

    await waitFor(() => {
      // The six fixed-card fetches of the previous filter set can still be in
      // flight; look for any call carrying the new filter combination.
      const match = mockedApi.performance.summary.mock.calls.find(
        ([query]) => query.symbol === 'xauusd' && query.direction === 'sell',
      );
      expect(match).toBeDefined();
    });

    // A custom range holds fetching until both dates are supplied.
    fireEvent.change(screen.getByTestId('perf-preset'), { target: { value: 'custom' } });
    expect(screen.getByTestId('perf-start')).toBeInTheDocument();
    expect(screen.getByTestId('perf-end')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('perf-reset'));
    expect(screen.getByTestId('perf-preset')).toHaveValue('d10');
    expect(screen.getByTestId('perf-symbol')).toHaveValue('');
  });

  it('selects a day from the daily table and lists that day\u2019s trades', async () => {
    render(<PerformancePanel />);

    await waitFor(() => {
      expect(screen.getByTestId('daily-perf-table')).toBeInTheDocument();
    });

    expect(screen.getByTestId('trades-day-no-selection')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('daily-select-2026-10-23'));

    expect(screen.getByTestId('trades-day-table')).toBeInTheDocument();
    expect(screen.getByTestId('trades-day-label')).toHaveTextContent('2026-10-23');
    expect(screen.getByText('#9911')).toBeInTheDocument();
    expect(screen.getByText('93451425, 93451600')).toBeInTheDocument();
  });

  it('shows the daily totals row and the cumulative chart from real rows', async () => {
    render(<PerformancePanel />);

    await waitFor(() => {
      expect(screen.getByTestId('daily-totals')).toBeInTheDocument();
    });
    expect(screen.getByTestId('daily-totals')).toHaveTextContent('2.65');
    expect(screen.getByTestId('cumulative-frame')).toBeInTheDocument();
    expect(screen.getByTestId('cumulative-caption')).toHaveTextContent('Asia/Kolkata');

    const trade = makePerformanceTrade({ close_day: '2026-10-23' });
    expect(trade.deal_tickets.length).toBeGreaterThan(0);
  });

  it('documents the accounting rule in the panel', async () => {
    render(<PerformancePanel />);

    await waitFor(() => {
      expect(screen.getByTestId('perf-accounting-rule')).toBeInTheDocument();
    });
    expect(screen.getByTestId('perf-accounting-rule')).toHaveTextContent(
      'How net P&L is calculated',
    );
  });
});
