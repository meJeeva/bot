import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from '../App';
import { makeHealth, makeSnapshot } from '../test/fixtures';

/**
 * Application wiring.
 *
 * Proves the minimal screen mounts against realistic backend payloads, reads
 * real MT5 data shapes, and never issues a non-GET request.
 */

// jsdom has no broker socket; the app falls back to the REST snapshot.
vi.mock('../services/websocket', () => ({
  MarketSocketClient: class {
    start(): void {}
    close(): void {}
  },
}));

function jsonResponse(payload: unknown): Response {
  return {
    ok: true,
    status: 200,
    text: async () => JSON.stringify(payload),
  } as unknown as Response;
}

const requests: Array<{ url: string; method: string }> = [];

function installFetch(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, method: init?.method ?? 'GET' });

      if (url.includes('/api/health')) {
        return jsonResponse(makeHealth());
      }
      if (url.includes('/api/market/snapshot')) {
        return jsonResponse(makeSnapshot());
      }
      return jsonResponse({});
    }),
  );
}

beforeEach(() => {
  requests.length = 0;
  installFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('App - read-only market data view', () => {
  it('renders the connection status and the live quote', async () => {
    render(<App />);

    expect(screen.getByRole('heading', { name: 'MT5 Market Data', level: 1 })).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId('overall-badge')).toBeInTheDocument();
      expect(screen.getByTestId('quote-bid')).toHaveTextContent('4185.58');
    });

    expect(screen.getByTestId('symbol-status')).toHaveTextContent('XAUUSD');
  });

  it('never issues a mutating request', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId('quote-bid')).toBeInTheDocument();
    });

    const nonGet = requests.filter((request) => request.method !== 'GET');
    expect(nonGet).toEqual([]);
    const forbidden = requests.filter(
      (request) =>
        request.url.includes('/execution') ||
        request.url.includes('/reports') ||
        request.url.includes('/backtest'),
    );
    expect(forbidden).toEqual([]);
  });
});
