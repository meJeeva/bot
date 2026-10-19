import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { makeEvents, makeSnapshot } from '../../test/fixtures';
import { EventLogPanel } from '../EventLogPanel';
import { formatDateTime } from '../../services/format';

describe('EventLogPanel - stream notice timestamp integrity', () => {
  const baseProps = {
    events: makeEvents(),
    snapshot: makeSnapshot(),
    streamNotice: null,
    noticeTimestamp: null,
    lastMessageAt: '2026-10-12T05:45:26.500Z',
    streamError: null,
  };

it('uses the provided backend noticeTimestamp for stream notices', () => {
    const backendTimestamp = '2026-10-12T05:45:26.500Z';
    render(
      <EventLogPanel
        {...baseProps}
        streamNotice='The market-data stream hit an internal error.'
        noticeTimestamp={backendTimestamp}
      />
    );

    // The stream notice should appear in the event log
    const noticeElement = screen.getByTestId('event-stream-notice');
    expect(noticeElement).toBeInTheDocument();
    expect(noticeElement).toHaveTextContent('The market-data stream hit an internal error.');

    // The timestamp displayed for the stream notice should be the backend timestamp,
    // not a client-generated one
    const marketElements = screen.getAllByText(/MARKET/i);
    // The last MARKET element should be the stream notice (not the market data one)
    const marketNoticeElement = marketElements[marketElements.length - 1].closest('div');
    // Should contain the formatted backend timestamp
    expect(marketNoticeElement).toHaveTextContent(formatDateTime(backendTimestamp));
  });

  it('falls back to "client-notice" label when no backend timestamp is provided', () => {
    render(
      <EventLogPanel
        {...baseProps}
        streamNotice='The market-data stream hit an internal error.'
        noticeTimestamp={null}
      />
    );

    // The stream notice should appear in the event log
    const noticeElement = screen.getByTestId('event-stream-notice');
    expect(noticeElement).toBeInTheDocument();

    // The event item should show the client-side notice label when no backend timestamp is provided
    const marketElements = screen.getAllByText(/MARKET/i);
    const marketNoticeElement = marketElements[marketElements.length - 1].closest('div');
    expect(marketNoticeElement).toHaveTextContent('Client-side notice (no backend timestamp)');
  });

  it('does not generate a client-side timestamp for stream notices', () => {
    render(
      <EventLogPanel
        {...baseProps}
        streamNotice='Test notice without backend timestamp'
        noticeTimestamp={null}
      />
    );

    // The displayed timestamp should NOT be a valid ISO timestamp close to the render time
    // (it should be the client-side notice label instead)
    const marketElements = screen.getAllByText(/MARKET/i);
    const marketNoticeElement = marketElements[marketElements.length - 1].closest('div');
    const text = (marketNoticeElement?.textContent) ?? '';

    // Should not contain a valid ISO timestamp close to render time
    expect(text).not.toMatch(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z/);
    expect(text).toContain('Client-side notice (no backend timestamp)');
  });

  it('preserves real backend event timestamps from connection events', () => {
    const snapshotWithConnectionError = makeSnapshot({
      connection: {
        ...makeSnapshot().connection,
        last_connection_error: '2026-10-12T05:10:00.000Z',
      },
    });

    render(<EventLogPanel {...baseProps} snapshot={snapshotWithConnectionError} />);

    // The connection error event should use the backend-provided timestamp
    const connectionErrorEvent = screen.getByText('MT5 connection error: 2026-10-12T05:10:00.000Z').closest('div');
    // The timestamp should be formatted from the backend value, not the server time offset
    expect(connectionErrorEvent).toHaveTextContent(formatDateTime('2026-10-12T05:10:00.000Z'));
  });

  it('preserves real backend event timestamps from strategy events', () => {
    const eventsWithStrategyEvent = makeEvents({
      events: [
        {
          timestamp: '2026-10-12T05:30:00.000Z',
          state: 'monitoring',
          initialized: true,
          connected: true,
          account_type: 'demo',
          symbol: 'XAUUSD',
          error: null,
        },
      ],
    });

    render(<EventLogPanel {...baseProps} events={eventsWithStrategyEvent} />);

    // The strategy event should use the backend-provided timestamp
    const strategyEvent = screen.getByText(/STRATEGY/i).closest('div');
    // The timestamp should be formatted from the backend value, not the raw ISO
    expect(strategyEvent).toHaveTextContent(formatDateTime('2026-10-12T05:30:00.000Z'));
  });
});