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

  trailing_mode?: string | null;
  atr_period?: number | null;
  atr_multiplier?: number | null;
  atr_value?: number | null;
  atr_distance?: number | null;
  atr_error?: string | null;
}
