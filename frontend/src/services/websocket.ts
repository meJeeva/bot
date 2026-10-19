/**
 * Reconnecting client for `WS /ws/market`.
 *
 * The backend pushes a snapshot on connect and again whenever market data
 * changes, plus periodic heartbeat frames. This client:
 *
 * * parses snapshot, heartbeat and error frames,
 * * reconnects automatically with capped exponential backoff so a backend
 *   restart does not require a page refresh,
 * * never throws out of an event handler, and
 * * accepts an injectable socket factory so it can be tested without a server.
 */

import type { MarketSnapshot, WsStatusMessage } from '../types/market';

/** Empty by default: derived from the page origin through the Vite proxy. */
export const WS_URL: string = import.meta.env.VITE_WS_URL ?? '';

export function marketWebSocketUrl(): string {
  if (WS_URL) {
    return WS_URL;
  }
  if (typeof window === 'undefined') {
    return 'ws://127.0.0.1:8000/ws/market';
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/ws/market`;
}

export interface MarketSocketHandlers {
  onSnapshot: (snapshot: MarketSnapshot) => void;
  onStatus?: (message: WsStatusMessage) => void;
  onOpen?: () => void;
  onClose?: (reason: string) => void;
}

export interface MarketSocketOptions {
  initialDelayMs?: number;
  maxDelayMs?: number;
  /** Injection point for tests. */
  socketFactory?: (url: string) => WebSocket;
}

export class MarketSocketClient {
  private socket: WebSocket | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private closed = true;
  private attempts = 0;

  private readonly factory: (url: string) => WebSocket;
  private readonly initialDelayMs: number;
  private readonly maxDelayMs: number;

  constructor(
    private readonly handlers: MarketSocketHandlers,
    options: MarketSocketOptions = {},
  ) {
    this.factory = options.socketFactory ?? ((url: string) => new WebSocket(url));
    this.initialDelayMs = options.initialDelayMs ?? 1_000;
    this.maxDelayMs = options.maxDelayMs ?? 15_000;
  }

  get reconnectAttempts(): number {
    return this.attempts;
  }

  start(): void {
    this.closed = false;
    this.connect();
  }

  close(): void {
    this.closed = true;
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      socket.onopen = null;
      socket.onmessage = null;
      socket.onclose = null;
      socket.onerror = null;
      try {
        socket.close();
      } catch {
        /* already closing */
      }
    }
  }

  private connect(): void {
    if (this.closed) {
      return;
    }

    let socket: WebSocket;
    try {
      socket = this.factory(marketWebSocketUrl());
    } catch {
      this.scheduleReconnect();
      return;
    }

    this.socket = socket;

    socket.onopen = () => {
      this.attempts = 0;
      this.handlers.onOpen?.();
    };

    socket.onmessage = (event: MessageEvent) => {
      this.dispatch(event.data);
    };

    socket.onclose = () => {
      this.socket = null;
      this.handlers.onClose?.('closed');
      this.scheduleReconnect();
    };

    socket.onerror = () => {
      // A close event always follows; reconnection is handled there.
    };
  }

  private dispatch(raw: unknown): void {
    if (typeof raw !== 'string') {
      return;
    }

    let payload: unknown;
    try {
      payload = JSON.parse(raw);
    } catch {
      return;
    }

    if (typeof payload !== 'object' || payload === null) {
      return;
    }

    const frame = payload as { type?: string };

    if (frame.type === 'snapshot') {
      this.handlers.onSnapshot(payload as MarketSnapshot);
      return;
    }

    if (frame.type === 'heartbeat' || frame.type === 'status' || frame.type === 'error') {
      this.handlers.onStatus?.(payload as WsStatusMessage);
    }
  }

  private scheduleReconnect(): void {
    if (this.closed) {
      return;
    }

    const delay = Math.min(this.initialDelayMs * 2 ** this.attempts, this.maxDelayMs);
    this.attempts += 1;

    this.timer = setTimeout(() => {
      this.timer = null;
      this.connect();
    }, delay);
  }
}
