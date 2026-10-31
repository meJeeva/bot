import { deriveOverallState } from '../services/dashboardState';
import type { HealthResponse, MarketSnapshot, StreamState } from '../types/market';
import { ConnectionStatusCard } from '../components/ConnectionStatusCard';
import { QuotePanel } from '../components/QuotePanel';
import { AutoTradingPanel } from '../components/AutoTradingPanel';
import { Pill, type PillTone } from '../components/terminal/ui';

const STATE_TONE: Record<string, PillTone> = {
  live: 'positive',
  stale: 'warning',
  reconnecting: 'warning',
  disconnected: 'negative',
  error: 'negative',
  loading: 'neutral',
};

export interface DashboardViewProps {
  health: HealthResponse | null;
  snapshot: MarketSnapshot | null;
  streamState: StreamState;
  streamError: string | null;
  streamNotice: string | null;
}

export function DashboardView({
  health,
  snapshot,
  streamState,
  streamError,
  streamNotice,
}: DashboardViewProps) {
  const overallState = deriveOverallState(snapshot, streamState);
  const quote = snapshot?.quote ?? null;
  const symbol = snapshot?.symbol?.resolved ?? snapshot?.symbol?.requested ?? null;
  const combinedError = streamError ?? snapshot?.last_error ?? null;

  return (
    <div className="dashboard">
      <header className="app-header">
        <div className="header-brand">
          <h1>MT5 Market Data</h1>
          <p className="subtitle">
            Automated trading dashboard
            {symbol ? ` · ${symbol}` : ''}
          </p>
        </div>
        <div className="header-status">
          <Pill tone={STATE_TONE[overallState] ?? 'neutral'} testId="overall-pill">
            {overallState}
          </Pill>
        </div>
      </header>

      {combinedError ? (
        <p className="alert alert-error" data-testid="global-error">
          {combinedError}
        </p>
      ) : null}

      <div className="dashboard-grid">
        <div className="dashboard-column">
          <ConnectionStatusCard
            state={overallState}
            snapshot={snapshot}
            health={health}
            streamNotice={streamNotice}
          />
          <QuotePanel quote={quote} />
        </div>
        <div className="dashboard-column">
          <AutoTradingPanel />
        </div>
      </div>

      <footer className="app-footer">
        <p>
          Data source: MetaTrader 5 desktop terminal via the official Python API.
        </p>
      </footer>
    </div>
  );
}