import { deriveOverallState } from '../services/dashboardState';
import type { HealthResponse, MarketSnapshot, StreamState } from '../types/market';
import { ConnectionStatusCard } from '../components/ConnectionStatusCard';
import { QuotePanel } from '../components/QuotePanel';
import { AutoTradingPanel } from '../components/AutoTradingPanel';
import { Pill, type PillTone } from '../components/terminal/ui';

/** Connection state as a pill tone. */
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

/**
 * The only screen: everything the application is allowed to do.
 *
 * The data comes from the backend's read-only endpoints. Nothing here can arm
 * an execution system, submit an order or change a setting, and an unavailable
 * value is rendered as unavailable rather than fabricated.
 */
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
        <div>
          <h1>MT5 Market Data</h1>
          <p className="subtitle">
            Read-only market data from the MetaTrader 5 terminal
            {symbol ? ` · ${symbol}` : ''}
          </p>
        </div>
        <div className="section-actions">
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

      <div className="card-grid">
        <ConnectionStatusCard
          state={overallState}
          snapshot={snapshot}
          health={health}
          streamNotice={streamNotice}
        />
        <QuotePanel quote={quote} />
        <AutoTradingPanel />
      </div>

      <footer className="app-footer">
        <p>
          Data source: MetaTrader 5 desktop terminal via the official Python API. Tick and bar times
          come from the broker server&apos;s clock; user-facing timestamps are labelled with the
          timezone they were converted to.
        </p>
        <p className="footnote">
          <strong>Read-only.</strong> This application never connects an execution system, never
          submits, modifies or closes an order, and never changes a backend setting. When the
          terminal is unavailable, missing prices are shown as unavailable rather than invented.
        </p>
      </footer>
    </div>
  );
}
