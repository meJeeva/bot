import { deriveOverallState } from '../services/dashboardState';
import type { HealthResponse, MarketSnapshot, StreamState } from '../types/market';
import { ConnectionStatusCard } from '../components/ConnectionStatusCard';
import { QuotePanel } from '../components/QuotePanel';
import { AutoTradingPanel } from '../components/AutoTradingPanel';
import { MetricStrip } from '../components/MetricStrip';
import { StrategyCyclePanel } from '../components/StrategyCyclePanel';
import { PriceLevelsPanel } from '../components/PriceLevelsPanel';
import { CycleHistoryPanel } from '../components/CycleHistoryPanel';
import { PriceChart, type ChartLevel } from '../components/PriceChart';
import { PerformancePanel } from '../components/PerformancePanel';
import { useAutoTradingStatus } from '../hooks/useAutoTradingStatus';
import { useCycleHistory } from '../hooks/useCycleHistory';
import { useCandles } from '../hooks/useCandles';
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

const CHART_TIMEFRAME = 'M1';
const CHART_LIMIT = 120;

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
 * Data comes from the backend's read-only endpoints. The market stream drives
 * the live quote and connection state; the auto-trading panels share one
 * status poll through `useAutoTradingStatus`. Nothing here can change a
 * setting, and an unavailable value is rendered as unavailable rather than
 * fabricated.
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
  const digits = snapshot?.symbol?.info?.digits ?? quote?.digits ?? null;
  const currency = snapshot?.connection?.account_currency ?? null;
  const combinedError = streamError ?? snapshot?.last_error ?? null;

  const auto = useAutoTradingStatus();
  const history = useCycleHistory();
  const candles = useCandles(CHART_TIMEFRAME, CHART_LIMIT);

  const chartLevels: ChartLevel[] = [
    { value: auto.status?.reference_value, label: 'Reference', tone: 'reference' },
    { value: auto.status?.buy_entry, label: 'Buy entry (strategy)', tone: 'buy' },
    { value: auto.status?.buy_sl, label: 'Buy initial SL (strategy)', tone: 'stop' },
    { value: auto.status?.sell_entry, label: 'Sell entry (strategy)', tone: 'sell' },
    { value: auto.status?.sell_sl, label: 'Sell initial SL (strategy)', tone: 'stop' },
    {
      value: auto.status?.break_even_active ? auto.status?.break_even_level : null,
      label: 'Break-even level (reported)',
      tone: 'protect',
    },
  ];

  const connectivity =
    overallState === 'live'
      ? 'Connected'
      : overallState === 'stale'
        ? 'Stale feed'
        : overallState === 'reconnecting'
          ? 'Reconnecting'
          : overallState === 'disconnected'
            ? 'Disconnected'
            : overallState === 'error'
              ? 'Error'
              : 'Loading';

  return (
    <div className="dashboard">
      <header className="app-header">
        <div>
          <h1>MT5 Market Data</h1>
          <p className="subtitle">
            Read-only market data from the MetaTrader 5 terminal
            {symbol ? ` · ${symbol}` : ''}
            {auto.status?.timeframe ? ` · ${auto.status.timeframe}` : ''}
          </p>
        </div>
        <div className="section-actions">
          <Pill tone={STATE_TONE[overallState] ?? 'neutral'} testId="overall-pill">
            {overallState}
          </Pill>
          {auto.status ? (
            <Pill
              tone={
                auto.status.status === 'RUNNING'
                  ? 'accent'
                  : auto.status.status === 'ERROR'
                    ? 'negative'
                    : 'neutral'
              }
              testId="worker-pill"
              title="Auto-trading worker state"
            >
              worker: {auto.status.status}
            </Pill>
          ) : null}
        </div>
      </header>

      {combinedError ? (
        <p className="alert alert-error" data-testid="global-error">
          {combinedError}
        </p>
      ) : null}

      <MetricStrip
        status={auto.status}
        currency={currency}
        connectivity={connectivity}
        connectivityHealthy={overallState === 'live'}
      />

      <div className="terminal-grid">
        <div className="terminal-grid-item span-8">
          <PriceChart
            series={candles.series}
            loading={!candles.loaded}
            error={candles.error}
            quote={quote}
            levels={chartLevels}
          />
        </div>
        <div className="terminal-grid-item span-4">
          <AutoTradingPanel
            status={auto.status}
            error={auto.error}
            busy={auto.busy}
            onStart={() => void auto.start()}
            onStop={() => void auto.stop()}
          />
        </div>

        <div className="terminal-grid-item span-4">
          <QuotePanel quote={quote} />
        </div>
        <div className="terminal-grid-item span-4">
          <StrategyCyclePanel status={auto.status} />
        </div>
        <div className="terminal-grid-item span-4">
          <PriceLevelsPanel status={auto.status} digits={digits} />
        </div>

        <div className="terminal-grid-item span-5">
          <ConnectionStatusCard
            state={overallState}
            snapshot={snapshot}
            health={health}
            streamNotice={streamNotice}
          />
        </div>
        <div className="terminal-grid-item span-7">
          <CycleHistoryPanel items={history.items} error={history.error} loaded={history.loaded} />
        </div>
      </div>

      <PerformancePanel />

      <footer className="app-footer">
        <p>
          Data source: MetaTrader 5 desktop terminal via the official Python API. Tick and bar times
          come from the broker server&apos;s clock; user-facing timestamps are labelled with the
          timezone they were converted to.
        </p>
        <p className="footnote">
          <strong>Read-only dashboard.</strong> The dashboard itself never submits, modifies or
          closes an order and never changes a backend setting; the Start and Stop controls drive the
          backend&apos;s existing auto-trading worker, which enforces its own demo-account,
          risk-limit and preflight protections. When the terminal is unavailable, missing prices are
          shown as unavailable rather than invented.
        </p>
      </footer>
    </div>
  );
}
