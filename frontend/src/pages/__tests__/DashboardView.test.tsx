import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { DashboardView, type DashboardViewProps } from '../DashboardView';
import { makeHealth, makeSnapshot, makeQuote } from '../../test/fixtures';

function baseProps(overrides: Partial<DashboardViewProps> = {}): DashboardViewProps {
  return {
    health: makeHealth(),
    snapshot: makeSnapshot(),
    streamState: 'connected',
    streamError: null,
    streamNotice: null,
    ...overrides,
  };
}

describe('DashboardView', () => {
  it('shows the MT5 connection state and the selected symbol', () => {
    render(<DashboardView {...baseProps()} />);

    expect(screen.getByTestId('overall-badge')).toHaveTextContent('Live');
    expect(screen.getByTestId('symbol-status')).toHaveTextContent('XAUUSD');
    expect(screen.getByTestId('terminal-status')).toHaveTextContent('connected');
  });

  it('renders the latest bid and ask', () => {
    render(<DashboardView {...baseProps()} />);

    expect(screen.getByTestId('quote-bid')).toHaveTextContent('4185.58');
    expect(screen.getByTestId('quote-ask')).toHaveTextContent('4186.14');
  });

  it('never invents prices when the terminal supplies none', () => {
    render(
      <DashboardView
        {...baseProps({
          snapshot: makeSnapshot({
            quote: null,
            data_status: 'unavailable',
            last_error: 'No executable tick has been received from MetaTrader 5 yet.',
          }),
        })}
      />,
    );

    expect(screen.getByTestId('quote-empty')).toBeInTheDocument();
    expect(screen.getByTestId('global-error')).toHaveTextContent('No executable tick');
  });

  it('shows an unavailable bid as a placeholder, not zero', () => {
    render(
      <DashboardView
        {...baseProps({
          snapshot: makeSnapshot({ quote: makeQuote({ bid: null }) }),
        })}
      />,
    );

    const bid = screen.getByTestId('quote-bid');
    expect(bid).toHaveTextContent('—');
    expect(bid).not.toHaveTextContent('0.00');
  });

  it('reports a disconnected terminal as a state, not an error', () => {
    render(
      <DashboardView
        {...baseProps({
          snapshot: makeSnapshot({
            connection: {
              ...makeSnapshot().connection,
              state: 'disconnected',
              mt5_initialized: false,
              terminal_connected: false,
            },
            quote: null,
            data_status: 'unavailable',
          }),
        })}
      />,
    );

    expect(screen.getByTestId('overall-badge')).toHaveTextContent('Disconnected');
  });
});
