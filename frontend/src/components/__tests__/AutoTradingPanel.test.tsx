import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { makeAutoTradingStatus } from '../../test/fixtures';
import { AutoTradingPanel } from '../AutoTradingPanel';

function baseProps(overrides: Partial<Parameters<typeof AutoTradingPanel>[0]> = {}) {
  return {
    status: makeAutoTradingStatus(),
    error: null,
    busy: false,
    onStart: vi.fn(),
    onStop: vi.fn(),
    ...overrides,
  };
}

describe('AutoTradingPanel', () => {
  it('shows the worker state the backend last reported', () => {
    render(<AutoTradingPanel {...baseProps()} />);

    expect(screen.getByTestId('auto-trading-status')).toHaveTextContent('RUNNING');
    expect(screen.getByTestId('auto-symbol')).toHaveTextContent('XAUUSD');
    expect(screen.getByTestId('auto-timeframe')).toHaveTextContent('M1');
  });

  it('disables Stop when the worker is stopped and enables it while running', () => {
    render(<AutoTradingPanel {...baseProps()} />);

    expect(screen.getByTestId('start-auto-trading')).toBeDisabled();
    expect(screen.getByTestId('stop-auto-trading')).toBeEnabled();
  });

  it('enables Start when the worker is stopped or in error', () => {
    render(
      <AutoTradingPanel {...baseProps({ status: makeAutoTradingStatus({ status: 'STOPPED' }) })} />,
    );

    expect(screen.getByTestId('start-auto-trading')).toBeEnabled();
    expect(screen.getByTestId('stop-auto-trading')).toBeDisabled();
  });

  it('enables Start after a backend error so the operator can retry deliberately', () => {
    render(
      <AutoTradingPanel {...baseProps({ status: makeAutoTradingStatus({ status: 'ERROR' }) })} />,
    );

    expect(screen.getByTestId('start-auto-trading')).toBeEnabled();
  });

  it('never starts on render and disables both controls while a request is in flight', () => {
    const onStart = vi.fn();
    render(<AutoTradingPanel {...baseProps({ busy: true, onStart })} />);

    expect(onStart).not.toHaveBeenCalled();
    expect(screen.getByTestId('start-auto-trading')).toBeDisabled();
    expect(screen.getByTestId('stop-auto-trading')).toBeDisabled();
    expect(screen.getByTestId('auto-trading-busy')).toBeInTheDocument();
  });

  it('surfaces a transport error without hiding the worker state', () => {
    render(
      <AutoTradingPanel {...baseProps({ error: 'Cannot reach the backend at /.' })} />,
    );

    expect(screen.getByTestId('auto-trading-error')).toHaveTextContent(
      'Cannot reach the backend at /.',
    );
    expect(screen.getByTestId('auto-trading-status')).toHaveTextContent('RUNNING');
  });

  it('shows the backend worker message verbatim instead of inventing a cause', () => {
    render(
      <AutoTradingPanel
        {...baseProps({
          status: makeAutoTradingStatus({ last_error: 'Maximum daily loss reached' }),
        })}
      />,
    );

    expect(screen.getByTestId('auto-last-error')).toHaveTextContent(
      'Maximum daily loss reached',
    );
  });

  it('renders missing execution values as placeholders, never as zero', () => {
    render(
      <AutoTradingPanel
        {...baseProps({
          status: makeAutoTradingStatus({
            entry_price: null,
            current_profit: null,
            entry_time: null,
            position_ticket: null,
          }),
        })}
      />,
    );

    expect(screen.getByTestId('auto-entry-price')).toHaveTextContent('—');
    expect(screen.getByTestId('auto-entry-price')).not.toHaveTextContent('0');
    expect(screen.getByTestId('auto-profit')).toHaveTextContent('—');
    expect(screen.getByTestId('auto-entry-time')).toHaveTextContent('—');
  });

  it('shows the signed floating P/L when the position is open', () => {
    render(
      <AutoTradingPanel
        {...baseProps({
          status: makeAutoTradingStatus({
            position_status: 'open',
            position_ticket: 5001,
            current_profit: -1.25,
          }),
        })}
      />,
    );

    expect(screen.getByTestId('auto-profit')).toHaveTextContent('-1.25');
    expect(screen.getByTestId('auto-position-ticket')).toHaveTextContent('#5001');
  });
});
