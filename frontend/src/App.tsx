/**
 * The application shell.
 *
 * One read-only screen over the backend's market-data API. It shows the MT5
 * connection state, the selected symbol and the current bid/ask. There is no
 * strategy, execution or account action: every request this app makes is a GET.
 */

import { useEffect, useState } from 'react';

import { useMarketStream } from './hooks/useMarketStream';
import { DashboardView } from './pages/DashboardView';
import { api } from './services/api';
import type { HealthResponse } from './types/market';

const HEALTH_POLL_MS = 10_000;

export function App() {
  const { snapshot, streamState, error: streamError, streamNotice } = useMarketStream();

  const [health, setHealth] = useState<HealthResponse | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    const load = async () => {
      try {
        const next = await api.health(controller.signal);
        if (!cancelled) {
          setHealth(next);
        }
      } catch {
        // Diagnostics are best-effort: the live stream is the real indicator.
      }
    };

    void load();
    const timer = window.setInterval(() => {
      void load();
    }, HEALTH_POLL_MS);

    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(timer);
    };
  }, []);

  return (
    <DashboardView
      health={health}
      snapshot={snapshot}
      streamState={streamState}
      streamError={streamError}
      streamNotice={streamNotice}
    />
  );
}

export default App;
