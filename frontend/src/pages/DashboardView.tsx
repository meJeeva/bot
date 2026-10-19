import { collectHealthIssues } from '../services/health';
import { deriveOverallState, type OverallState } from '../services/dashboardState';
import type {
  Candle,
  CandleSeries,
  ConnectionEventsResponse,
  HealthResponse,
  MarketSnapshot,
  StreamState,
  Timeframe,
} from '../types/market';
import type { ExecutionHistoryOut, ExecutionStatusOut, RiskStatusOut } from '../types/execution';
import { MarketOverview, CompactHeader } from '../components/MarketOverview';
import { TimeframePanel } from '../components/TimeframePanel';
import { ExecutionStatusPanel } from '../components/ExecutionStatusPanel';
import { RiskAndAccountPanel } from '../components/RiskAndAccountPanel';

export interface DashboardViewProps {
  // Market data
  health: HealthResponse | null;
  snapshot: MarketSnapshot | null;
  streamState: StreamState;
  streamError: string | null;
  streamNotice: string | null;
  noticeTimestamp: string | null;
  lastMessageAt: string | null;
  events: ConnectionEventsResponse | null;

  // Timeframe & chart
  timeframe: Timeframe;
  onTimeframeChange: (timeframe: Timeframe) => void;
  candles: Candle[];
  series: CandleSeries | null;
  candlesLoading: boolean;
  candlesError: string | null;
  onRefreshHistory: () => void;

  // Execution & risk
  executionStatus: ExecutionStatusOut | null;
  riskStatus: RiskStatusOut | null;
  executionHistory: ExecutionHistoryOut | null;
  executionLoading: boolean;
  executionError: string | null;
  onRefreshExecution: () => void;
}

/**
 * Single-page unified dashboard.
 *
 * All sections are stacked vertically in one page:
 * 1. Compact header
 * 2. Market overview
 * 3. Main chart with 7 timeframes
 * 4. Execution & risk (read-only)
 *
 * The trading strategies have been removed, so there is no strategy section.
 */
export function DashboardView(props: DashboardViewProps) {
  const overallState: OverallState = deriveOverallState(props.snapshot, props.streamState);
  const combinedError = props.candlesError ?? props.streamError;

  const quote = props.snapshot?.quote ?? null;

  // Account info is not available from the read-only API.
  const accountEquity = null;
  const accountBalance = null;
  const todayPnl = null;
  const openPositions = 0;
  const entriesUsedToday = 0;

  // Health issues (computed for the preserved system-health monitoring).
  collectHealthIssues({
    streamState: props.streamState,
    streamError: props.streamError,
    streamNotice: props.streamNotice,
    events: props.events,
    snapshot: props.snapshot,
    health: props.health,
    candlesError: props.candlesError,
    executionStatus: props.executionStatus,
  });

  return (
    <div className="dashboard" data-overall-state={overallState}>
      {/* 1. Compact Header */}
      <CompactHeader
        snapshot={props.snapshot}
        streamState={props.streamState}
        streamError={props.streamError}
        lastMessageAt={props.lastMessageAt}
        health={props.health}
      />

      {combinedError ? (
        <p className="alert alert-error" data-testid="global-error">
          {combinedError}
        </p>
      ) : null}

      {/* 2. Market Overview */}
      <MarketOverview
        snapshot={props.snapshot}
        quote={quote}
        accountEquity={accountEquity}
        accountBalance={accountBalance}
        todayPnl={todayPnl}
        openPositions={openPositions}
        entriesUsedToday={entriesUsedToday}
      />

      {/* 3. Main Chart with 7 Timeframes */}
      <TimeframePanel
        timeframe={props.timeframe}
        onTimeframeChange={props.onTimeframeChange}
        summaries={props.snapshot?.timeframes ?? {}}
        summary={props.snapshot?.timeframes?.[props.timeframe] ?? null}
        candles={props.candles}
        loading={props.candlesLoading}
        error={props.candlesError}
        symbol={props.snapshot?.symbol?.resolved ?? props.series?.symbol ?? null}
        onRefresh={props.onRefreshHistory}
      />

      {/* 4. Execution & Risk (read-only) */}
      <section className="section" aria-labelledby="execution-risk-heading">
        <header className="section-header">
          <h2 id="execution-risk-heading">Execution & Risk</h2>
        </header>
        {props.executionError && (
          <p className="alert alert-error" data-testid="execution-error">
            {props.executionError}
          </p>
        )}
        <div className="card-grid">
          <ExecutionStatusPanel status={props.executionStatus} onRefresh={props.onRefreshExecution} />
          <RiskAndAccountPanel risk={props.riskStatus} />
        </div>
      </section>

      <footer className="app-footer">
        <p>
          Data source: MetaTrader 5 desktop terminal via the official Python API. Timestamps are
          displayed in Indian Standard Time (Asia/Kolkata).
        </p>
        <p className="footnote">
          <strong>Read-only dashboard.</strong> No orders are placed, modified or closed. No trading
          strategy is configured. Execution is disabled by default and requires explicit operator
          arming.
        </p>
      </footer>
    </div>
  );
}
