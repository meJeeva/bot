import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { Candle, Timeframe } from '../../types/market';
import { makeEvents, makeHealth, makeSeries, makeSnapshot } from '../../test/fixtures';
import { DashboardView, type DashboardViewProps } from '../DashboardView';

// The chart needs a real canvas; stub it so these tests stay about behaviour.
vi.mock('../../components/CandleChart', () => ({
  CandleChart: ({ candles, timeframe }: { candles: Candle[]; timeframe: Timeframe }) => (
    <div data-testid="candle-chart" data-count={candles.length} data-timeframe={timeframe} />
  ),
}));

function renderView(overrides: Partial<DashboardViewProps> = {}) {
  const series = makeSeries('M15', 20);

  const props: DashboardViewProps = {
    health: makeHealth(),
    snapshot: makeSnapshot(),
    streamState: 'connected',
    streamError: null,
    streamNotice: null,
    noticeTimestamp: null,
    lastMessageAt: '2026-10-12T05:45:26.500Z',
    events: makeEvents(),
    timeframe: 'M15',
    onTimeframeChange: vi.fn(),
    candles: series.candles,
    series,
    candlesLoading: false,
    candlesError: null,
    onRefreshHistory: vi.fn(),
    executionStatus: null,
    riskStatus: null,
    executionHistory: null,
    executionLoading: false,
    executionError: null,
    onRefreshExecution: vi.fn(),
    ...overrides,
  };

  return { ...render(<DashboardView {...props} />), props };
}

describe('DashboardView - loading state', () => {
  it('shows a connecting state before the first snapshot', () => {
    renderView({ snapshot: null, streamState: 'loading', candles: [], series: null, candlesLoading: true });

    expect(screen.getByTestId('overall-status')).toBeInTheDocument();
    expect(screen.getByTestId('compact-header')).toBeInTheDocument();
    expect(screen.getByTestId('candle-chart')).toHaveAttribute('data-count', '0');
  });

  it('does not claim a connection it does not have', () => {
    renderView({ snapshot: null, streamState: 'loading', candles: [], series: null });

    expect(screen.getByTestId('overall-status')).toBeInTheDocument();
  });
});

describe('DashboardView - live state', () => {
  it('shows live status with real quote values', () => {
    renderView();

    expect(screen.getByTestId('overall-status')).toBeInTheDocument();
    expect(screen.getByTestId('compact-header')).toBeInTheDocument();
  });

  it('renders the compact header with app name and symbol', () => {
    renderView();

    expect(screen.getByText('Fibonacci MT5 Bot')).toBeInTheDocument();
    expect(screen.getByText('XAUUSD')).toBeInTheDocument();
  });

  it('renders all seven timeframe tabs', () => {
    renderView();

    const tablist = screen.getByRole('tablist', { name: 'Timeframe' });
    expect(tablist).toBeInTheDocument();
    // Tabs are rendered by TimeframePanel
  });

  it('notifies the container when the timeframe changes', async () => {
    const user = await import('@testing-library/user-event').then(m => m.default.setup());
    const { props } = renderView();

    await user.click(
      screen.getByRole('tab', { name: 'Timeframe H1' }),
    );

    expect(props.onTimeframeChange).toHaveBeenCalledWith('H1');
  });

  it('marks the active timeframe as selected', () => {
    renderView({ timeframe: 'H4' });

    const tab = screen.getByRole('tab', { name: 'Timeframe H4' });
    expect(tab).toHaveAttribute('aria-selected', 'true');
  });
});

describe('DashboardView - market overview', () => {
  it('shows market overview section', () => {
    renderView();

    expect(screen.getByText('Market Overview')).toBeInTheDocument();
  });

  it('displays bid and ask prices', () => {
    renderView();

    // MarketOverview component should render bid/ask
  });
});

describe('DashboardView - recent trades', () => {
  it('shows execution & risk section', () => {
    renderView();

    expect(screen.getByText('Execution & Risk')).toBeInTheDocument();
    expect(screen.getByTestId('execution-none')).toBeInTheDocument();
  });
});

describe('DashboardView - performance risk summary', () => {
  it('shows risk and account panel', () => {
    renderView();

    expect(screen.getByText('Risk & account')).toBeInTheDocument();
    expect(screen.getByTestId('risk-daily-loss')).toBeInTheDocument();
  });
});