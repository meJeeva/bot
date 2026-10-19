import { describe, expect, it } from 'vitest';

import { makeQuote, makeSnapshot } from '../../test/fixtures';
import { deriveOverallState, describeOverallState } from '../dashboardState';

describe('deriveOverallState', () => {
  it('is loading before the first snapshot arrives', () => {
    expect(deriveOverallState(null, 'loading')).toBe('loading');
  });

  it('is live only when the terminal is connected AND the tick is fresh', () => {
    expect(deriveOverallState(makeSnapshot(), 'connected')).toBe('live');
  });

  it('is stale when the terminal is connected but the backend reports stale data', () => {
    const snapshot = makeSnapshot({ data_status: 'stale', quote: makeQuote({ freshness: 'stale', is_stale: true }) });

    expect(deriveOverallState(snapshot, 'connected')).toBe('stale');
  });

  it('is stale when the terminal is connected but no tick has arrived', () => {
    const snapshot = makeSnapshot({ data_status: 'unavailable', quote: null });

    expect(deriveOverallState(snapshot, 'connected')).toBe('stale');
  });

  it('never reports live when the quote itself is not fresh', () => {
    const snapshot = makeSnapshot({
      data_status: 'live', // backend claim
      quote: makeQuote({ freshness: 'unknown', is_stale: true }), // but the tick is not fresh
    });

    expect(deriveOverallState(snapshot, 'connected')).not.toBe('live');
  });

  it('never reports live when the terminal is not connected', () => {
    const snapshot = makeSnapshot();
    snapshot.connection.terminal_connected = false;

    expect(deriveOverallState(snapshot, 'connected')).not.toBe('live');
  });

  it('is disconnected when MT5 was never initialized', () => {
    const snapshot = makeSnapshot();
    snapshot.connection.mt5_initialized = false;

    expect(deriveOverallState(snapshot, 'connected')).toBe('disconnected');
  });

  it('is reconnecting while the backend retries the terminal', () => {
    const snapshot = makeSnapshot();
    snapshot.connection.reconnecting = true;
    snapshot.connection.state = 'reconnecting';
    snapshot.connection.terminal_connected = false;
    snapshot.data_status = 'stale';

    expect(deriveOverallState(snapshot, 'connected')).toBe('reconnecting');
  });

  it('is error when the backend reported a fatal connection error', () => {
    const snapshot = makeSnapshot();
    snapshot.connection.state = 'error';

    expect(deriveOverallState(snapshot, 'connected')).toBe('error');
  });

  it('is error when the WebSocket itself failed', () => {
    expect(deriveOverallState(makeSnapshot(), 'error')).toBe('error');
  });
});

describe('describeOverallState', () => {
  it('marks only the live state as healthy', () => {
    const states = [
      'loading',
      'live',
      'stale',
      'reconnecting',
      'disconnected',
      'error',
    ] as const;

    for (const state of states) {
      const descriptor = describeOverallState(state, makeSnapshot());
      expect(descriptor.state).toBe(state);
      expect(descriptor.healthy).toBe(state === 'live');
      expect(descriptor.label.length).toBeGreaterThan(0);
      expect(descriptor.detail.length).toBeGreaterThan(0);
    }
  });

  it('surfaces the backend error text when available', () => {
    const snapshot = makeSnapshot({ last_error: 'No usable tick was returned.' });
    const descriptor = describeOverallState('stale', snapshot);

    expect(descriptor.detail).toBe('No usable tick was returned.');
  });

  it('falls back to the connection error when there is no snapshot error', () => {
    const snapshot = makeSnapshot();
    snapshot.connection.last_connection_error = 'Terminal closed unexpectedly';

    expect(describeOverallState('disconnected', snapshot).detail).toBe(
      'Terminal closed unexpectedly',
    );
  });

  it('works without a snapshot at all', () => {
    expect(describeOverallState('loading', null).detail).toContain('Waiting');
  });
});
