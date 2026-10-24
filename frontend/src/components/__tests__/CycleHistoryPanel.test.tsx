import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { makeHistoryItem } from '../../test/fixtures';
import { CycleHistoryPanel } from '../CycleHistoryPanel';

describe('CycleHistoryPanel', () => {
  it('lists recorded cycles newest first', () => {
    const older = makeHistoryItem({
      cycle_id: 's-4',
      exit_time: '2026-10-12T05:43:02.000Z',
    });
    const newer = makeHistoryItem({
      cycle_id: 's-6',
      exit_time: '2026-10-12T05:47:02.000Z',
    });

    render(<CycleHistoryPanel items={[older, newer]} error={null} loaded />);

    expect(screen.getByTestId('history-count')).toHaveTextContent('showing 2 of 2');
    const ids = screen.getAllByTestId('history-cycle-id');
    expect(ids[0]).toHaveTextContent('s-6');
    expect(ids[1]).toHaveTextContent('s-4');
  });

  it('renders the realized profit with an explicit sign and tone', () => {
    render(
      <CycleHistoryPanel
        items={[
          makeHistoryItem({ profit: -1.0 }),
          makeHistoryItem({ cycle_id: 's-3', profit: 2.5 }),
        ]}
        error={null}
        loaded
      />,
    );

    expect(screen.getByText('-1.00')).toHaveClass('text-red');
    expect(screen.getByText('+2.50')).toHaveClass('text-green');
  });

  it('shows the designed empty state when the backend reports no history', () => {
    render(<CycleHistoryPanel items={[]} error={null} loaded />);

    expect(screen.getByTestId('history-empty')).toBeInTheDocument();
    expect(screen.getByTestId('history-empty')).toHaveTextContent('No cycle history yet');
  });

  it('keeps the loading and error states distinct from the empty state', () => {
    const { unmount } = render(<CycleHistoryPanel items={[]} error={null} loaded={false} />);
    expect(screen.getByTestId('history-loading')).toBeInTheDocument();
    unmount();

    render(
      <CycleHistoryPanel items={[]} error="Cannot reach the backend at /." loaded />,
    );
    expect(screen.getByTestId('history-error')).toHaveTextContent('History is temporarily unavailable');
    expect(screen.queryByTestId('history-empty')).not.toBeInTheDocument();
  });

  it('caps the table instead of rendering an unbounded list', () => {
    const items = Array.from({ length: 40 }, (_, index) =>
      makeHistoryItem({ cycle_id: `s-${index}`, exit_time: `2026-10-12T0${index % 10}:00:00.000Z` }),
    );

    render(<CycleHistoryPanel items={items} error={null} loaded />);

    expect(screen.getByTestId('history-count')).toHaveTextContent('showing 25 of 40');
    expect(screen.getAllByTestId('history-cycle-id')).toHaveLength(25);
  });

  it('carries the backend error text on the row for an errored cycle', () => {
    render(
      <CycleHistoryPanel
        items={[makeHistoryItem({ status: 'error', error: 'Exit rejected: retcode=10015' })]}
        error={null}
        loaded
      />,
    );

    const row = screen.getByTestId('history-cycle-id').closest('tr');
    expect(row).not.toBeNull();
    expect(row).toHaveAttribute('title', 'Exit rejected: retcode=10015');
    expect(screen.getByText('error')).toBeInTheDocument();
  });
});
