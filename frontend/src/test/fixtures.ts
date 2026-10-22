/**
 * Test fixtures.
 *
 * Defaults mirror what the real backend returns for a healthy XAUUSD feed
 * (2 digits, 0.01 point, MetaQuotes-Demo at UTC+3), so component tests exercise
 * realistic shapes rather than convenient ones.
 */

import type {
  Candle,
  HealthResponse,
  MarketSnapshot,
  Quote,
  Timeframe,
  TimeframeSummary,
} from '../types/market';

const BROKER_OFFSET_SECONDS = 10800;

export function makeCandle(overrides: Partial<Candle> = {}): Candle {
  const time = overrides.time ?? 1_791_794_700;
  const openTimeBroker =
    overrides.open_time_broker ?? new Date((time + BROKER_OFFSET_SECONDS) * 1_000).toISOString();
  const openTimeUtc = overrides.open_time_utc ?? new Date(time * 1_000).toISOString();

  return {
    time,
    open_time_broker: openTimeBroker,
    open_time_utc: openTimeUtc,
    open: 4187.32,
    high: 4187.9,
    low: 4186.13,
    close: 4186.41,
    tick_volume: 87,
    spread_points: 31,
    real_volume: 0,
    is_closed: true,
    ...overrides,
  };
}

export function makeQuote(overrides: Partial<Quote> = {}): Quote {
  return {
    symbol: 'XAUUSD',
    bid: 4185.58,
    ask: 4186.14,
    last: null,
    spread_price: 0.56,
    spread_points: 56,
    point: 0.01,
    digits: 2,
    tick_size: 0.01,
    tick_value: 0.1,
    tick_time_broker: '2026-10-12T08:45:26.000Z',
    tick_time_utc: '2026-10-12T05:45:26.000Z',
    age_seconds: 0.4,
    freshness: 'live',
    is_stale: false,
    received_at: '2026-10-12T05:45:26.400Z',
    server_time_offset_seconds: BROKER_OFFSET_SECONDS,
    ...overrides,
  };
}

export function makeTimeframeSummary(overrides: Partial<TimeframeSummary> = {}): TimeframeSummary {
  return {
    timeframe: 'M15',
    seconds: 900,
    latest_closed: makeCandle(),
    forming: makeCandle({ time: 1_791_795_600, is_closed: false, close: 4187.1 }),
    candle_count: 300,
    last_updated: '2026-10-12T05:45:20.000Z',
    error: null,
    ...overrides,
  };
}

function allTimeframes(): Record<string, TimeframeSummary> {
  const names: Timeframe[] = ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1'];
  const seconds: Record<Timeframe, number> = {
    M1: 60,
    M5: 300,
    M15: 900,
    M30: 1800,
    H1: 3600,
    H4: 14400,
    D1: 86400,
  };
  return Object.fromEntries(
    names.map((name) => [name, makeTimeframeSummary({ timeframe: name, seconds: seconds[name] })]),
  );
}

export function makeSnapshot(overrides: Partial<MarketSnapshot> = {}): MarketSnapshot {
  return {
    type: 'snapshot',
    sequence: 42,
    generated_at: '2026-10-12T05:45:26.500Z',
    connection: {
      state: 'connected',
      mt5_initialized: true,
      terminal_connected: true,
      terminal_path: 'C:\\Program Files\\MetaTrader 5',
      terminal_name: 'MetaTrader 5',
      terminal_company: 'MetaQuotes Ltd.',
      terminal_build: 6140,
      terminal_language: 'English',
      trading_server: 'MetaQuotes-Demo',
      account_login_masked: '******7615',
      account_login: null,
      account_currency: 'USD',
      account_type: 'demo',
      account_trade_mode: 0,
      last_connected_at: '2026-10-12T05:40:00.000Z',
      last_connection_error: null,
      last_market_data_at: '2026-10-12T05:45:26.400Z',
      reconnecting: false,
      reconnect_attempts: 0,
      next_reconnect_at: null,
      server_time_offset_seconds: BROKER_OFFSET_SECONDS,
      time_convention: 'broker_server_local',
      trading_enabled: false,
      read_only: true,
      timestamp: '2026-10-12T05:45:26.500Z',
    },
    symbol: {
      requested: 'XAUUSD',
      resolved: 'XAUUSD',
      resolution: 'resolved',
      matched_by: 'exact',
      modifier: null,
      message: 'Symbol resolved exactly as configured.',
      candidates: ['XAUUSD'],
      requires_configuration: false,
      info: {
        name: 'XAUUSD',
        digits: 2,
        point: 0.01,
        tick_size: 0.01,
        tick_value: 0.1,
        broker_spread_points: 56,
        currency_base: 'XAU',
        currency_profit: 'USD',
      },
    },
    quote: makeQuote(),
    data_status: 'live',
    last_market_update: '2026-10-12T05:45:26.400Z',
    quote_age_seconds: 0.4,
    timeframes: allTimeframes(),
    last_error: null,
    trading_enabled: false,
    read_only: true,
    ...overrides,
  };
}

export function makeHealth(overrides: Partial<HealthResponse> = {}): HealthResponse {
  return {
    status: 'ok',
    app_name: 'MT5 Market Data',
    version: '0.1.0',
    environment: 'development',
    started_at: '2026-10-12T05:40:00.000Z',
    uptime_seconds: 326,
    read_only: true,
    trading_enabled: false,
    mt5_initialized: true,
    terminal_connected: true,
    data_status: 'live',
    timestamp: '2026-10-12T05:45:26.500Z',
    ...overrides,
  };
}
