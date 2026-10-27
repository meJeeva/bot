import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { makeAutoTradingStatus } from '../../test/fixtures';
import { StrategyCyclePanel } from '../StrategyCyclePanel';

describe('StrategyCyclePanel', () => {
  it('marks exactly one step active from the backend strategy phase', () => {
    render(<StrategyCyclePanel status={makeAutoTradingStatus({ strategy_phase: 'WAITING_ENTRY' })} />);

    const active = screen.getByTestId('cycle-step-value');
    expect(active).toHaveClass('step-active');
    // Preparing completes before the entries are armed.
    expect(screen.getByTestId('cycle-step-initializing')).toHaveClass('step-done');
    expect(screen.getByTestId('cycle-step-removing')).toHaveClass('step-upcoming');
    expect(screen.getByTestId('cycle-step-switching')).toHaveClass('step-upcoming');
    expect(screen.getByTestId('cycle-phase-pill')).toHaveTextContent('WAITING_ENTRY');
  });

  it('shows the removing phase as active and earlier phases as done', () => {
    render(
      <StrategyCyclePanel
        status={makeAutoTradingStatus({ strategy_phase: 'BUY_OPEN', position_ticket: 5001 })}
      />,
    );

    expect(screen.getByTestId('cycle-step-value')).toHaveClass('step-done');
    expect(screen.getByTestId('cycle-step-removing')).toHaveClass('step-active');
    expect(screen.getByTestId('cycle-step-switching')).toHaveClass('step-upcoming');
    expect(screen.getByTestId('cycle-position-open')).toHaveTextContent('yes · #5001');
  });

  it('renders an unknown backend phase verbatim instead of guessing a step', () => {
    render(
      <StrategyCyclePanel status={makeAutoTradingStatus({ strategy_phase: 'SOMETHING_NEW' })} />,
    );

    expect(screen.getByTestId('cycle-phase-pill')).toHaveTextContent('SOMETHING_NEW');
    expect(screen.getByTestId('cycle-phase-unknown')).toBeInTheDocument();
    expect(screen.queryByTestId('cycle-step-value')).not.toHaveClass('step-active');
  });

  it('renders an ERROR phase with the negative pill', () => {
    render(
      <StrategyCyclePanel
        status={makeAutoTradingStatus({ strategy_phase: 'ERROR', status: 'ERROR' })}
      />,
    );

    expect(screen.getByTestId('cycle-phase-pill')).toHaveTextContent('ERROR');
  });

  it('shows a genuine ERROR with the backend reason, not an unmapped-phase guess', () => {
    render(
      <StrategyCyclePanel
        status={makeAutoTradingStatus({
          status: 'ERROR',
          strategy_phase: 'ERROR',
          last_error: 'SELL Stop rejected: retcode=10016 comment=invalid stops',
        })}
      />,
    );

    expect(screen.getByTestId('cycle-phase-error')).toBeInTheDocument();
    expect(screen.getByTestId('cycle-error-reason')).toHaveTextContent(
      'SELL Stop rejected: retcode=10016 comment=invalid stops',
    );
    // A fatal state is reported as itself, never as an unknown cycle step.
    expect(screen.queryByTestId('cycle-phase-unknown')).not.toBeInTheDocument();
    expect(screen.queryByTestId('cycle-step-removing')).not.toHaveClass('step-active');
  });

  it('shows the spread-blocked state with the measured and configured points', () => {
    render(
      <StrategyCyclePanel
        status={makeAutoTradingStatus({
          strategy_phase: 'SPREAD_BLOCKED',
          profile: 'BTCUSD',
          symbol: 'BTCUSD.m',
          spread_blocked: true,
          spread_points: 858,
          max_spread_points: 100,
          last_error: 'Spread exceeds maximum: 858 points > 100 configured',
        })}
      />,
    );

    expect(screen.getByTestId('cycle-phase-pill')).toHaveTextContent('SPREAD_BLOCKED');
    expect(screen.getByTestId('cycle-spread-blocked')).toBeInTheDocument();
    expect(screen.getByTestId('cycle-spread-blocked-reason')).toHaveTextContent(
      '858 points > 100 configured',
    );
    expect(screen.getByTestId('cycle-spread-comparison')).toHaveTextContent(
      'Measured 858 points against a configured maximum of 100 points.',
    );
    // Blocked entries are not an error and not an unmapped phase.
    expect(screen.queryByTestId('cycle-phase-error')).not.toBeInTheDocument();
    expect(screen.queryByTestId('cycle-phase-unknown')).not.toBeInTheDocument();
    expect(screen.getByTestId('cycle-phase-pill')).toHaveClass('pill-warning');
  });

  it('reports blocked entries even while an armed cycle keeps its own phase', () => {
    render(
      <StrategyCyclePanel
        status={makeAutoTradingStatus({
          strategy_phase: 'WAITING_ENTRY',
          spread_blocked: true,
          spread_points: 1200,
          max_spread_points: 100,
          last_error: 'Spread exceeds maximum: 1200 points > 100 configured',
        })}
      />,
    );

    expect(screen.getByTestId('cycle-step-value')).toHaveClass('step-active');
    expect(screen.getByTestId('cycle-spread-blocked')).toBeInTheDocument();
  });

  it('does not show an error or blocked notice for a normal cycle step', () => {
    render(<StrategyCyclePanel status={makeAutoTradingStatus()} />);

    expect(screen.queryByTestId('cycle-phase-error')).not.toBeInTheDocument();
    expect(screen.queryByTestId('cycle-spread-blocked')).not.toBeInTheDocument();
    expect(screen.queryByTestId('cycle-phase-unknown')).not.toBeInTheDocument();
  });

  it('shows the cycle context values the backend supplies', () => {
    render(
      <StrategyCyclePanel
        status={makeAutoTradingStatus({ cycle_id: 's-20261012-054000-5', reference_value: 4186.14 })}
      />,
    );

    expect(screen.getByTestId('cycle-id')).toHaveTextContent('s-20261012-054000-5');
    expect(screen.getByTestId('cycle-reference')).toHaveTextContent('4186.14');
  });

  it('reports the unavailable status honestly when nothing has loaded', () => {
    render(<StrategyCyclePanel status={null} />);

    expect(screen.getByTestId('cycle-empty')).toBeInTheDocument();
    expect(screen.getByTestId('cycle-phase-pill')).toHaveTextContent('unknown');
  });
});
