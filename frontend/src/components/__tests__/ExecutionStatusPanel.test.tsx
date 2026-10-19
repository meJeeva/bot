import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ExecutionStatusPanel } from '../ExecutionStatusPanel';
import type { ExecutionStatusOut } from '../../types/execution';

describe('ExecutionStatusPanel', () => {
  const mockExecutionStatus: ExecutionStatusOut = {
    mode: 'disabled',
    configured: false,
    armed: false,
    demo_verified: false,
    account_type: null,
    account_login_masked: null,
    account_server: null,
    account_currency: null,
    reasons: [],
    last_verified_at: '2026-10-12T05:45:26.000Z',
    armed_at: null,
    last_error: null,
    daily_lockout: null,
    drawdown_lockout: null,
    consecutive_losses: 0,
    unresolved_executions: 0,
    last_reconciled_at: null,
    total_executions: 0,
    open_bot_positions: 0,
    persistence_available: false,
    signal_source: 'live_strategy',
    trading_enabled: false,
    live_trading_supported: false,
    timestamp: '2026-10-12T05:45:26.000Z',
  };

  afterEach(() => {
    cleanup();
  });

  it('shows loading state when status is null', () => {
    render(<ExecutionStatusPanel status={null} onRefresh={vi.fn()} />);

    expect(
      screen.getByTestId('execution-none')
    ).toHaveTextContent('Loading execution status...');
  });

  it('displays execution status when present', () => {
    render(
      <ExecutionStatusPanel
        status={mockExecutionStatus}
        onRefresh={vi.fn()}
      />
    );

    // Check that the status information is displayed
    expect(screen.getByTestId('execution-mode')).toHaveTextContent('Disabled');
    expect(screen.getByTestId('execution-configured')).toHaveTextContent('No');
    expect(screen.getByTestId('execution-demo-verified')).toHaveTextContent('No');
    expect(screen.getByTestId('execution-armed')).toHaveTextContent('No');
    expect(
      screen.getByTestId('execution-last-verified')
    ).toHaveTextContent('12/10/2026, 11:15:26 am IST');
    expect(screen.getByTestId('execution-armed-at')).toHaveTextContent('—');
    expect(screen.getByTestId('execution-no-reasons')).toHaveTextContent(
      'No restrictions recorded.'
    );
  });

  it('calls onRefresh when Refresh button is clicked', async () => {
    const onRefresh = vi.fn();
    render(
      <ExecutionStatusPanel
        status={mockExecutionStatus}
        onRefresh={onRefresh}
      />
    );

    const refreshButton = screen.getByTestId(
      'execution-refresh-button'
    );
    expect(refreshButton).toBeInTheDocument();
    expect(refreshButton).toHaveTextContent('Refresh');

    // Click the refresh button
    const user = userEvent.setup();
    await user.click(refreshButton);

    // Verify the onRefresh callback was called
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it('displays error state when present', () => {
    const statusWithError = {
      ...mockExecutionStatus,
      last_error: 'API error: Connection timeout',
    };

    render(
      <ExecutionStatusPanel
        status={statusWithError}
        onRefresh={vi.fn()}
      />
    );

    expect(
      screen.getByTestId('execution-last-error')
    ).toHaveTextContent('API error: Connection timeout');
    expect(screen.getByTestId('execution-last-error')).toHaveClass(
      'alert alert-error'
    );
  });

  it('does not arm execution or submit orders (read-only)', () => {
    render(
      <ExecutionStatusPanel
        status={mockExecutionStatus}
        onRefresh={vi.fn()}
      />
    );

    // Verify there are no buttons that would arm or submit orders
    const actionButtons = screen.queryAllByRole('button', {
      name: /arm|enable|trade|submit|order|cancel|close|modify/i,
    });
    expect(actionButtons).toHaveLength(0);

    // The only button should be the Refresh button
    const refreshButtons = screen.getAllByRole('button', {
      name: /refresh/i,
    });
    expect(refreshButtons).toHaveLength(1);
  });
});