/**
 * Subscribes the dashboard to the backend's live market-data stream.
 *
 * Two sources are combined:
 * 1. an initial REST snapshot, so the page renders even before the socket
 *    finishes its handshake, and
 * 2. the `WS /ws/market` stream, which then drives every update.
 *
 * The socket reconnects on its own; this hook only reflects that state.
 */

import { useEffect, useMemo, useRef, useState } from 'react';

import { describeError, api } from '../services/api';
import { MarketSocketClient, type MarketSocketOptions } from '../services/websocket';
import type { MarketSnapshot, StreamState } from '../types/market';

export interface MarketStreamResult {
  streamState: StreamState;
  snapshot: MarketSnapshot | null;
  error: string | null;
  lastMessageAt: string | null;
  /** Non-empty when the last frame was a backend error frame. */
  streamNotice: string | null;
  /** Backend timestamp from the WsStatusMessage that set streamNotice. */
  noticeTimestamp: string | null;
}

export interface UseMarketStreamOptions extends MarketSocketOptions {
  /** Poll `/api/market/snapshot` as a fallback while the socket is down. */
  snapshotPollMs?: number;
}

export function useMarketStream(options: UseMarketStreamOptions = {}): MarketStreamResult {
  const { snapshotPollMs = 5_000, ...socketOptions } = options;

  const [snapshot, setSnapshot] = useState<MarketSnapshot | null>(null);
  const [streamState, setStreamState] = useState<StreamState>('loading');
  const [error, setError] = useState<string | null>(null);
  const [streamNotice, setStreamNotice] = useState<string | null>(null);
  const [noticeTimestamp, setNoticeTimestamp] = useState<string | null>(null);
  const [lastMessageAt, setLastMessageAt] = useState<string | null>(null);

  // Keep the latest socket options without re-creating the socket each render.
  const optionsRef = useRef(socketOptions);
  optionsRef.current = socketOptions;

  const client = useMemo(() => {
    return new MarketSocketClient(
      {
        onSnapshot: (next) => {
          setSnapshot(next);
          setError(null);
          setStreamNotice(null);
          setStreamState('connected');
          setLastMessageAt(new Date().toISOString());
        },
onStatus: (message) => {
        if (message.type === 'heartbeat') {
          setStreamState('connected');
          setLastMessageAt(new Date().toISOString());
          return;
        }
        if (message.type === 'error') {
          setStreamNotice(message.message);
          setNoticeTimestamp(message.timestamp ?? null);
        }
      },
        onOpen: () => {
          setStreamState('connected');
          setError(null);
        },
        onClose: () => {
          setStreamState((current) => (current === 'error' ? current : 'reconnecting'));
        },
      },
      optionsRef.current,
    );
  }, []);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const loadInitialSnapshot = async () => {
      try {
        const initial = await api.snapshot(controller.signal);
        if (!cancelled) {
          setSnapshot(initial);
          setError(null);
        }
      } catch (cause) {
        if (!cancelled) {
          setError(describeError(cause));
        }
      }
    };

    void loadInitialSnapshot();
    client.start();

    // While the socket is unavailable, keep polling so the page still shows
    // real data rather than a frozen one.
    const poll = window.setInterval(() => {
      void loadInitialSnapshot();
    }, snapshotPollMs);

    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(poll);
      client.close();
    };
  }, [client, snapshotPollMs]);

  return { streamState, snapshot, error, lastMessageAt, streamNotice, noticeTimestamp };
}
