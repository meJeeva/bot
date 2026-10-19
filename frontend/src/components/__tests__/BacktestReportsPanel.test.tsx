import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import {
  makeBacktestDetail,
  makeBacktestReports,
  makeBacktestRun,
} from '../../test/fixtures';
import { BacktestReportsPanel, type BacktestReportsPanelProps } from '../BacktestReportsPanel';

function renderPanel(overrides: Partial<BacktestReportsPanelProps> = {}) {
  const props: BacktestReportsPanelProps = {
    reports: makeBacktestReports(),
    loading: false,
    error: null,
    selectedRunId: null,
    detail: null,
    detailLoading: false,
    detailError: null,
    onSelectRun: vi.fn(),
    onRefresh: vi.fn(),
    ...overrides,
  };
  return { ...render(<BacktestReportsPanel {...props} />), props };
}

describe('BacktestReportsPanel', () => {
  it('states that results are historical simulation only', () => {
    renderPanel();

    expect(screen.getByTestId('backtest-disclaimer')).toHaveTextContent('Historical simulation only');
    expect(screen.getByTestId('backtest-disclaimer')).toHaveTextContent('never starts or overwrites');
  });

  it('lists the report runs with their provenance', () => {
    renderPanel();

    const table = screen.getByTestId('backtest-runs');
    expect(table).toHaveTextContent('xauusd_20260414_20261014_4eea7638');
    expect(table).toHaveTextContent('Per-timeframe backtest');
    expect(table).toHaveTextContent('XAUUSD');
    expect(screen.getByTestId('backtest-root')).toHaveTextContent('reports/backtests');
  });

  it('selects a run when View is clicked', async () => {
    const user = userEvent.setup();
    const { props } = renderPanel();

    await user.click(screen.getByTestId('backtest-view-xauusd_20260414_20261014_4eea7638'));

    expect(props.onSelectRun).toHaveBeenCalledWith('xauusd_20260414_20261014_4eea7638');
  });

  it('shows the run detail with per-timeframe results and download links', () => {
    renderPanel({
      selectedRunId: 'xauusd_20260414_20261014_4eea7638',
      detail: makeBacktestDetail(),
    });

    expect(screen.getByTestId('backtest-detail')).toBeInTheDocument();
    const tf = screen.getByTestId('backtest-timeframes');
    expect(tf).toHaveTextContent('M15');
    expect(tf).toHaveTextContent('established');

    const artifacts = screen.getByTestId('backtest-artifacts');
    const links = artifacts.querySelectorAll('a');
    expect(links.length).toBe(2);
    expect(links[0].getAttribute('href')).toContain('/api/reports');
    expect(links[0].getAttribute('href')).toContain('/files/');
  });

  it('reports a missing reports directory honestly', () => {
    renderPanel({ reports: makeBacktestReports({ available: false, runs: [], count: 0 }) });

    expect(screen.getByTestId('backtest-unavailable')).toHaveTextContent('No reports directory');
  });

  it('shows an empty state for an empty reports directory', () => {
    renderPanel({ reports: makeBacktestReports({ available: true, runs: [], count: 0 }) });

    expect(screen.getByTestId('backtest-empty')).toBeInTheDocument();
  });

  it('surfaces a load error without faking results', () => {
    renderPanel({ reports: null, error: 'backend down' });

    expect(screen.getByTestId('backtest-error')).toHaveTextContent('backend down');
    expect(screen.queryByTestId('backtest-runs')).not.toBeInTheDocument();
  });

  it('renders a run without a parseable summary without crashing', () => {
    renderPanel({
      reports: makeBacktestReports({
        runs: [makeBacktestRun({ summary_available: false, strategy_fingerprint: null })],
      }),
    });

    expect(screen.getByTestId('backtest-runs')).toHaveTextContent('xauusd_20260414_20261014_4eea7638');
  });

  it('refreshes on demand', async () => {
    const user = userEvent.setup();
    const { props } = renderPanel();

    await user.click(screen.getByRole('button', { name: 'Refresh' }));

    expect(props.onRefresh).toHaveBeenCalled();
  });
});
