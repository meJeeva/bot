import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  MarketSocketClient,
  marketWebSocketUrl,
} from '../websocket';
import { makeSnapshot } from '../../test/fixtures';

/* ------------------------------------------------------------------ */
/* Fake WebSocket                                                      */
/* ------------------------------------------------------------------ */

class FakeSocket {
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(public readonly url: string) {
    sockets.push(this);
  }

  close(): void {
    this.closed = true;
  }

  emit(payload: unknown): void {
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent);
  }
}

let sockets: FakeSocket[] = [];
const socketFactory = (url: string): WebSocket => new FakeSocket(url) as unknown as WebSocket;

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  sockets = [];
});

describe('websocket URL construction', () => {
  it('builds the market endpoint', () => {
    expect(marketWebSocketUrl()).toMatch(/\/ws\/market$/);
  });
});

describe('MarketSocketClient regression', () => {
  it('still connects to /ws/market and delivers snapshots', () => {
    const onSnapshot = vi.fn();
    const client = new MarketSocketClient({ onSnapshot }, { socketFactory });
    client.start();

    expect(sockets[0].url).toMatch(/\/ws\/market$/);

    const frame = makeSnapshot();
    sockets[0].emit(frame);

    expect(onSnapshot).toHaveBeenCalledTimes(1);
    expect(onSnapshot.mock.calls[0][0].type).toBe('snapshot');
    client.close();
  });

  it('still routes heartbeat frames to onStatus', () => {
    const onSnapshot = vi.fn();
    const onStatus = vi.fn();
    const client = new MarketSocketClient({ onSnapshot, onStatus }, { socketFactory });
    client.start();

    sockets[0].emit({ type: 'heartbeat', message: 'stream alive' });

    expect(onStatus).toHaveBeenCalledTimes(1);
    expect(onSnapshot).not.toHaveBeenCalled();
    client.close();
  });
});
