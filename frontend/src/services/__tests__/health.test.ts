import { describe, expect, it } from 'vitest';

import { collectHealthIssues, healthIssueCount, type HealthInput } from '../health';
import { makeEvents, makeHealth, makeSnapshot } from '../../test/fixtures';

function input(overrides: Partial<HealthInput> = {}): HealthInput {
  return {
    streamState: 'connected',
    streamError: null,
    streamNotice: null,
    events: null,
    snapshot: makeSnapshot(),
    health: makeHealth(),
    candlesError: null,
    executionStatus: null,
    ...overrides,
  };
}

describe('collectHealthIssues', () => {
  it('reports no issues for a healthy system', () => {
    expect(collectHealthIssues(input())).toEqual([]);
    expect(healthIssueCount([])).toBe(0);
  });

  it('surfaces the backend being unreachable as an error', () => {
    const issues = collectHealthIssues(
      input({ snapshot: null, health: null, streamState: 'loading', streamError: 'boom' }),
    );
    const backend = issues.find((issue) => issue.id === 'backend-unreachable');
    expect(backend?.severity).toBe('error');
    expect(backend?.message).toBe('boom');
  });

  it('reports a stream error and a reconnect as distinct issues', () => {
    expect(
      collectHealthIssues(input({ streamState: 'error', streamError: 'socket died' })).some(
        (issue) => issue.id === 'stream-error' && issue.severity === 'error',
      ),
    ).toBe(true);

    expect(
      collectHealthIssues(input({ streamState: 'reconnecting' })).some(
        (issue) => issue.id === 'stream-reconnecting',
      ),
    ).toBe(true);
  });

  it('reports stale market data', () => {
    const snapshot = makeSnapshot({ data_status: 'stale' });
    const issues = collectHealthIssues(input({ snapshot }));
    expect(issues.some((issue) => issue.id === 'market-stale')).toBe(true);
  });

  it('caps and groups repetitive recorded connection errors', () => {
    const events = makeEvents({
      errors: Array.from({ length: 6 }, (_, index) => ({
        timestamp: `2026-10-12T05:0${index}:00.000Z`,
        state: 'error',
        initialized: false,
        connected: false,
        account_type: 'demo',
        symbol: 'XAUUSD',
        error: `failure ${index}`,
      })),
    });

    const issues = collectHealthIssues(input({ events }));
    const recorded = issues.filter((issue) => issue.source === 'Connection events');
    // Three shown plus one grouped "more" line.
    expect(recorded.filter((issue) => issue.severity === 'error')).toHaveLength(3);
    expect(recorded.some((issue) => issue.id === 'recorded-errors-more')).toBe(true);
  });

  it('deduplicates identical issues and orders errors first', () => {
    const issues = collectHealthIssues(
      input({
        streamState: 'error',
        streamError: 'same',
        streamNotice: 'warning',
        executionStatus: {
          mode: 'blocked',
          configured: true,
          armed: false,
          demo_verified: false,
          account_type: null,
          account_login_masked: null,
          account_server: null,
          account_currency: null,
          reasons: ['demo not verified'],
          last_verified_at: null,
          armed_at: null,
          last_error: null,
          daily_lockout: null,
          drawdown_lockout: null,
          consecutive_losses: 0,
          unresolved_executions: 0,
          last_reconciled_at: null,
          total_executions: 0,
          open_bot_positions: 0,
          persistence_available: true,
          signal_source: 'live_strategy',
          trading_enabled: false,
          live_trading_supported: false,
          timestamp: '2026-10-14T00:00:00Z',
        },
      }),
    );

    expect(issues.some((issue) => issue.id === 'stream-error')).toBe(true);
    expect(issues.some((issue) => issue.id === 'stream-notice')).toBe(true);
    expect(issues.some((issue) => issue.id === 'execution-blocked')).toBe(true);
    // Errors sort before warnings/info.
    const severities = issues.map((issue) => issue.severity);
    expect(severities.indexOf('error')).toBeLessThan(severities.indexOf('warning'));
  });
});
