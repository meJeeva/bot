import { formatDateTime, formatNumber, formatPrice } from '../services/format';
import type { MarketSnapshot, Quote, DataStatus } from '../types/market';

export interface CompactHeaderProps {
  snapshot: MarketSnapshot | null;
  streamState: 'loading' | 'connected' | 'reconnecting' | 'error';
  streamError: string | null;
  lastMessageAt: string | null;
  health: { status: string; mt5_initialized: boolean; terminal_connected: boolean; data_status: DataStatus; timestamp: string } | null;
}

function getConnectionStateClass(state: DataStatus | 'loading' | 'connected' | 'reconnecting' | 'error'): string {
  switch (state) {
    case 'live':
    case 'connected':
      return 'status-live';
    case 'stale':
    case 'reconnecting':
      return 'status-stale';
    case 'unavailable':
    case 'error':
    case 'loading':
      return 'status-error';
    default:
      return 'status-unknown';
  }
}

function getConnectionStateLabel(state: DataStatus | 'loading' | 'connected' | 'reconnecting' | 'error'): string {
  switch (state) {
    case 'live': return 'LIVE';
    case 'stale': return 'STALE';
    case 'unavailable': return 'UNAVAILABLE';
    case 'loading': return 'LOADING';
    case 'connected': return 'CONNECTED';
    case 'reconnecting': return 'RECONNECTING';
    case 'error': return 'ERROR';
    default: return 'UNKNOWN';
  }
}

export function CompactHeader({
  snapshot,
  streamState,
  streamError,
  lastMessageAt,
  health,
}: CompactHeaderProps) {
  const connection = snapshot?.connection;
  const quote = snapshot?.quote;
  const dataStatus = snapshot?.data_status ?? 'unavailable';
  const overallState = streamState === 'connected' && dataStatus === 'live' ? 'live' : 
                       streamState === 'reconnecting' || dataStatus === 'stale' ? 'stale' : 'error';
  
  const lastUpdate = lastMessageAt 
    ? formatDateTime(lastMessageAt) 
    : snapshot?.last_market_update 
    ? formatDateTime(snapshot.last_market_update) 
    : '—';

  return (
    <header className="compact-header" data-testid="compact-header">
      <div className="header-left">
        <h1 className="app-title">Fibonacci MT5 Bot</h1>
        <span className="symbol-badge">XAUUSD</span>
      </div>

      <div className="header-center">
        <div className={`status-indicator ${getConnectionStateClass(overallState)}`} data-testid="overall-status">
          <span className="status-dot" />
          <span className="status-text">{getConnectionStateLabel(overallState)}</span>
        </div>
        
        <div className="status-item mt5-status">
          <span className="status-label">MT5</span>
          <span className={`status-value ${connection?.terminal_connected ? 'connected' : 'disconnected'}`}>
            {connection?.terminal_connected ? 'Connected' : 'Disconnected'}
          </span>
        </div>

        <div className="status-item backend-status">
          <span className="status-label">Backend</span>
          <span className={`status-value ${health?.status === 'ok' ? 'healthy' : 'degraded'}`}>
            {health?.status === 'ok' ? 'Healthy' : health?.status ?? 'Unknown'}
          </span>
        </div>

        <div className="status-item data-freshness">
          <span className="status-label">Data</span>
          <span className={`status-value ${getConnectionStateClass(dataStatus)}`}>
            {getConnectionStateLabel(dataStatus)}
          </span>
        </div>

        <div className="status-item last-update">
          <span className="status-label">Last Update</span>
          <span className="status-value mono">{lastUpdate}</span>
        </div>

        {streamError && (
          <div className="status-item stream-error">
            <span className="status-label">Stream Error</span>
            <span className="status-value error mono">{streamError}</span>
          </div>
        )}
      </div>

      <div className="header-right">
        {quote && (
          <>
            <div className="quote-mini bid">
              <span className="quote-label">Bid</span>
              <span className="quote-value mono">{formatPrice(quote.bid ?? 0, 5)}</span>
            </div>
            <div className="quote-mini ask">
              <span className="quote-label">Ask</span>
              <span className="quote-value mono">{formatPrice(quote.ask ?? 0, 5)}</span>
            </div>
            <div className="quote-mini spread">
              <span className="quote-label">Spread</span>
              <span className="quote-value mono">
                {quote.spread_points !== null ? `${quote.spread_points} pts` : '—'}
              </span>
            </div>
          </>
        )}
      </div>
    </header>
  );
}

export interface MarketOverviewProps {
  snapshot: MarketSnapshot | null;
  quote: Quote | null;
  accountEquity: number | null;
  accountBalance: number | null;
  todayPnl: number | null;
  openPositions: number;
  entriesUsedToday: number;
}

export function MarketOverview({
  snapshot,
  quote,
  accountEquity,
  accountBalance,
  todayPnl,
  openPositions,
  entriesUsedToday,
}: MarketOverviewProps) {
  const spread = quote?.spread_points ?? null;
  const spreadPrice = quote?.spread_price ?? null;

  return (
    <section className="card market-overview" aria-labelledby="market-overview-heading">
      <header className="card-header">
        <h2 id="market-overview-heading">Market Overview</h2>
      </header>

      <div className="market-grid">
        <div className="market-item">
          <dt>Bid</dt>
          <dd className="mono bid">{quote?.bid !== null && quote?.bid !== undefined ? formatPrice(quote.bid, 5) : '—'}</dd>
        </div>
        <div className="market-item">
          <dt>Ask</dt>
          <dd className="mono ask">{quote?.ask !== null && quote?.ask !== undefined ? formatPrice(quote.ask, 5) : '—'}</dd>
        </div>
        <div className="market-item">
          <dt>Spread</dt>
          <dd className="mono">
            {spread !== null ? `${spread} pts` : spreadPrice !== null ? `${formatPrice(spreadPrice, 5)}` : '—'}
          </dd>
        </div>
        <div className="market-item">
          <dt>Equity</dt>
          <dd className="mono">{accountEquity !== null ? `$${formatNumber(accountEquity, 2)}` : '—'}</dd>
        </div>
        <div className="market-item">
          <dt>Balance</dt>
          <dd className="mono">{accountBalance !== null ? `$${formatNumber(accountBalance, 2)}` : '—'}</dd>
        </div>
        <div className="market-item">
          <dt>Today's P&L</dt>
          <dd className={`mono ${todayPnl !== null && todayPnl < 0 ? 'text-red' : todayPnl !== null && todayPnl > 0 ? 'text-green' : ''}`}>
            {todayPnl !== null ? `${todayPnl >= 0 ? '+' : ''}$${formatNumber(todayPnl, 2)}` : '—'}
          </dd>
        </div>
        <div className="market-item">
          <dt>Open Positions</dt>
          <dd className="mono">{openPositions}</dd>
        </div>
        <div className="market-item">
          <dt>Entries Used Today</dt>
          <dd className="mono">{entriesUsedToday}</dd>
        </div>
      </div>

      {snapshot?.connection && (
        <div className="market-meta">
          <span className="meta-item">Server: {snapshot.connection.trading_server ?? '—'}</span>
          <span className="meta-item">Account: {snapshot.connection.account_login_masked ?? '—'}</span>
          <span className="meta-item">Currency: {snapshot.connection.account_currency ?? '—'}</span>
          <span className="meta-item">Type: {snapshot.connection.account_type ?? '—'}</span>
        </div>
      )}
    </section>
  );
}