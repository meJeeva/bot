import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { makeAutoTradingStatus } from '../../test/fixtures';
import { MetricStrip } from '../MetricStrip';

function baseProps(overrides: Partial<Parameters<typeof MetricStrip>[0]> = {}) {
  return {
    status: makeAutoTradingStatus(),
    currency: 'USD',
    connectivity: 'Connected',
    connectivityHealthy: true,
    ...overrides,
  };
}

describe('MetricStrip', () => {
  it('shows the account values with their currency and the worker state', () => {
    render(<MetricStrip {...baseProps()} />);

    expect(screen.getByTestId('metric-balance')).toHaveTextContent('10,000.00');
    expect(screen.getByTestId('metric-balance')).toHaveTextContent('USD');
    expect(screen.getByTestId('metric-equity')).toHaveTextContent('10,000.00');
    expect(screen.getByTestId('metric-worker')).toHaveTextContent('RUNNING');
    expect(screen.getByTestId('metric-connectivity')).toHaveTextContent('Connected');
  });

  it('renders an open position and its floating P/L', () => {
    render(
      <MetricStrip
        {...baseProps({
          status: makeAutoTradingStatus({
            position_status: 'open',
            position_ticket: 5001,
            current_profit: -1.25,
          }),
        })}
      />,
    );

    expect(screen.getByTestId('metric-position')).toHaveTextContent('#5001');
    expect(screen.getByTestId('metric-pnl')).toHaveTextContent('-1.25');
  });

  it('renders a flat position and unavailable P/L honestly', () => {
    render(<MetricStrip {...baseProps()} />);

    expect(screen.getByTestId('metric-position')).toHaveTextContent('none');
    expect(screen.getByTestId('metric-pnl')).toHaveTextContent('—');
    expect(screen.getByTestId('metric-pnl')).not.toHaveTextContent('0.00');
  });

  it('degrades to placeholders when no status has loaded yet', () => {
    render(<MetricStrip {...baseProps({ status: null, currency: null })} />);

    expect(screen.getByTestId('metric-balance')).toHaveTextContent('—');
    expect(screen.getByTestId('metric-equity')).toHaveTextContent('—');
    expect(screen.getByTestId('metric-worker')).toHaveTextContent('—');
  });

  it('counts cycles for the worker and the session separately', () => {
    render(
      <MetricStrip
        {...baseProps({
          status: makeAutoTradingStatus({ completed_cycles: 12, session_completed_cycles: 4 }),
        })}
      />,
    );

    expect(screen.getByTestId('metric-cycles')).toHaveTextContent('12');
    expect(screen.getByTestId('metric-cycles')).toHaveTextContent('4 this session');
  });
});
