/**
 * Types mirroring the backend Pydantic schemas.
 *
 * Deliberately hand-written and narrow rather than generated, so the dashboard
 * fails loudly at compile time if the API contract changes.
 *
 * Nullability matters here: the backend reports unavailable values as `null`,
 * never as `0` or a fabricated price, and the UI must preserve that.
 */

export type Timeframe = 'M1' | 'M5' | 'M15' | 'M30' | 'H1' | 'H4' | 'D1';

/** Freshness of the market data the backend is holding. */
export type DataStatus = 'live' | 'stale' | 'unavailable';

/** Coarse MT5 connection state. */
export type ConnectionState =
  | 'connected'
  | 'connecting'
  | 'reconnecting'
  | 'disconnected'
  | 'error';

/** State of the dashboard's own WebSocket link to the backend. */
export type StreamState = 'loading' | 'connected' | 'reconnecting' | 'error';

export type AccountType = 'demo' | 'live' | 'unknown';

export interface SymbolInfo {
  name: string;
  digits: number;
  point: number;
  tick_size: number | null;
  tick_value: number | null;
  broker_spread_points: number | null;
  currency_base: string | null;
  currency_profit: string | null;
}

export interface SymbolStatus {
  requested: string;
  resolved: string | null;
  resolution: 'resolved' | 'ambiguous' | 'not_found' | 'unavailable' | 'pending';
  matched_by: string | null;
  modifier: string | null;
  message: string;
  candidates: string[];
  requires_configuration: boolean;
  info: SymbolInfo | null;
}

export interface MT5Status {
  state: ConnectionState;
  mt5_initialized: boolean;
  terminal_connected: boolean;
  terminal_path: string | null;
  terminal_name: string | null;
  terminal_company: string | null;
  terminal_build: number | null;
  terminal_language: string | null;
  trading_server: string | null;
  account_login_masked: string | null;
  account_login: number | null;
  account_currency: string | null;
  account_type: AccountType;
  account_trade_mode: number | null;
  last_connected_at: string | null;
  last_connection_error: string | null;
  last_market_data_at: string | null;
  reconnecting: boolean;
  reconnect_attempts: number;
  next_reconnect_at: string | null;
  server_time_offset_seconds: number | null;
  time_convention: string;
  trading_enabled: boolean;
  read_only: boolean;
  timestamp: string;
}

export interface Quote {
  symbol: string;
  bid: number | null;
  ask: number | null;
  last: number | null;
  spread_price: number | null;
  spread_points: number | null;
  point: number;
  digits: number;
  tick_size: number | null;
  tick_value: number | null;
  tick_time_broker: string | null;
  tick_time_utc: string | null;
  age_seconds: number | null;
  freshness: 'live' | 'stale' | 'unknown';
  is_stale: boolean;
  received_at: string;
  server_time_offset_seconds: number | null;
}

export interface Candle {
  /** Raw MetaTrader value: broker-server seconds since the epoch. */
  time: number;
  open_time_broker: string;
  open_time_utc: string;
  open: number;
  high: number;
  low: number;
  close: number;
  tick_volume: number;
  spread_points: number | null;
  real_volume: number | null;
  /** False for the bar that is still forming. */
  is_closed: boolean;
}

export interface TimeframeSummary {
  timeframe: Timeframe;
  seconds: number;
  latest_closed: Candle | null;
  forming: Candle | null;
  candle_count: number;
  last_updated: string | null;
  error: string | null;
}

export interface MarketSnapshot {
  type: 'snapshot';
  sequence: number;
  generated_at: string;
  connection: MT5Status;
  symbol: SymbolStatus;
  quote: Quote | null;
  data_status: DataStatus;
  last_market_update: string | null;
  quote_age_seconds: number | null;
  timeframes: Record<string, TimeframeSummary>;
  last_error: string | null;
  trading_enabled: boolean;
  read_only: boolean;
}

/** `GET /api/market/candles` payload. */
export interface CandleSeries {
  symbol: string;
  timeframe: string;
  timeframe_seconds: number;
  requested_limit: number;
  count: number;
  candles: Candle[];
  latest_candle: Candle | null;
  latest_closed_candle: Candle | null;
  server_time_offset_seconds: number | null;
  time_convention: string;
  incomplete_history: boolean;
  warnings: string[];
  generated_at: string;
}

/** One completed (or attempted) strategy cycle from the history endpoint. */
export interface AutoTradingHistoryItem {
  cycle_id: string;
  symbol: string | null;
  entry_time: string | null;
  exit_time: string | null;
  entry_price: number | null;
  exit_price: number | null;
  volume: number | null;
  profit: number | null;
  status: string;
  error: string | null;
}

export interface AutoTradingHistoryResponse {
  items: AutoTradingHistoryItem[];
  history: AutoTradingHistoryItem[];
  count: number;
}

/* -------------------------------------------------------------------------
 * Performance reporting (`GET /api/performance/*`, read-only).
 * Mirrors backend/app/schemas/performance.py. All amounts come from MT5
 * deal history; `data_available: false` means the history could not be read
 * and the UI must show "unavailable" rather than zeros.
 * ------------------------------------------------------------------------- */

export interface PerformanceCosts {
  commission: number;
  swap: number;
  fee: number;
  total: number;
}

export interface FloatingPnl {
  open_positions: number;
  profit: number;
  swap: number;
  total: number;
}

export interface CashMovement {
  ticket: number;
  type_code: number;
  type_name: string;
  time: string | null;
  amount: number;
  comment: string | null;
}

export interface PerformanceFilters {
  preset: string | null;
  start: string | null;
  end: string | null;
  symbol: string | null;
  direction: 'buy' | 'sell' | null;
  magic: number | null;
}

export interface PerformanceSummary {
  data_available: boolean;
  error: string | null;
  range_start: string;
  range_end: string;
  reporting_timezone: string;
  broker_time_offset_seconds: number | null;
  time_convention: string;
  account_currency: string | null;
  balance: number | null;
  equity: number | null;
  closed_trades: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  gross_pnl: number;
  costs: PerformanceCosts;
  net_pnl: number;
  floating: FloatingPnl;
  cash_movements: CashMovement[];
  cash_movements_total: number;
  deals_checked: number;
  positions_matched: number;
  filters: PerformanceFilters;
  accounting_rule: string;
  generated_at: string;
}

export interface DailyPerformanceItem {
  date: string;
  closed_trades: number;
  wins: number;
  losses: number;
  gross_pnl: number;
  costs: PerformanceCosts;
  net_pnl: number;
  win_rate: number | null;
}

export interface DailyPerformanceResponse {
  data_available: boolean;
  error: string | null;
  range_start: string;
  range_end: string;
  reporting_timezone: string;
  account_currency: string | null;
  days: DailyPerformanceItem[];
  totals: DailyPerformanceItem | null;
  filters: PerformanceFilters;
  generated_at: string;
}

export interface PerformanceTrade {
  position_id: number;
  symbol: string | null;
  direction: 'buy' | 'sell' | null;
  magic: number | null;
  comment: string | null;
  opened_volume: number;
  closed_volume: number;
  entry_time: string | null;
  exit_time: string | null;
  entry_price: number | null;
  exit_price: number | null;
  gross_pnl: number;
  costs: PerformanceCosts;
  net_pnl: number;
  deal_tickets: number[];
  order_tickets: number[];
  close_day: string | null;
}

export interface PerformanceTradesResponse {
  data_available: boolean;
  error: string | null;
  reporting_timezone: string;
  account_currency: string | null;
  trades: PerformanceTrade[];
  count: number;
  filters: PerformanceFilters;
  generated_at: string;
}

/** Query parameters accepted by every `/api/performance/*` endpoint. */
export interface PerformanceQuery {
  preset?: string;
  start?: string;
  end?: string;
  symbol?: string;
  direction?: 'buy' | 'sell';
  magic?: number;
}

export interface HealthResponse {
  status: 'ok' | 'degraded';
  app_name: string;
  version: string;
  environment: string;
  started_at: string;
  uptime_seconds: number;
  read_only: boolean;
  trading_enabled: boolean;
  mt5_initialized: boolean;
  terminal_connected: boolean;
  data_status: DataStatus;
  timestamp: string;
}

export interface WsStatusMessage {
  type: 'status' | 'error' | 'heartbeat';
  message: string;
  code: string | null;
  timestamp: string;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    detail: unknown;
  };
}

export interface AutoTradingStatus {
  status: string;
  auto_trading_status?: string;
  trading_status?: string;
  state?: string;

  symbol: string | null;
  timeframe: string;
  connection_status: string | null;
  terminal_connected: boolean;
  trading_enabled: boolean;

  balance: number | null;
  equity: number | null;

  position_status: string;
  position_state?: string;
  position_ticket: number | null;
  ticket?: number | null;
  entry_price: number | null;
  entry_time: string | null;
  current_profit: number | null;
  profit?: number | null;
  unrealized_pnl?: number | null;

  last_entry_result: string | null;
  last_exit_result: string | null;

  next_cycle: string | null;
  next_scheduled_cycle?: string | null;
  next_cycle_at?: string | null;

  completed_cycles: number;
  session_completed_cycles?: number;
  cycles_completed?: number;
  successful_entries: number;
  failed_entries: number;
  failed_exits: number;

  last_error: string | null;
  error?: string | null;

  session_id: string | null;
  cycle_id: string | null;
  magic_number: number | null;

  strategy_phase?: string | null;
  /** Active instrument profile (`XAUUSD` / `BTCUSD`) the backend resolved. */
  profile?: string | null;
  /** True while the live spread is above the configured maximum. */
  spread_blocked?: boolean;
  /** Last measured spread in points, and the configured limit, same unit. */
  spread_points?: number | null;
  max_spread_points?: number | null;
  active_side?: string | null;
  reference_value?: number | null;
  buy_entry?: number | null;
  buy_sl?: number | null;
  sell_entry?: number | null;
  sell_sl?: number | null;
  buy_order_ticket?: number | null;
  sell_order_ticket?: number | null;
  highest_favorable_price?: number | null;
  lowest_favorable_price?: number | null;
  break_even_active?: boolean;
  break_even_level?: number | null;
  last_processed_deal?: unknown;
  previous_cycle_complete?: boolean;
}
