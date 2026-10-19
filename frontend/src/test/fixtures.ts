/**
 * Test fixtures.
 *
 * Defaults mirror what the real backend returns for a healthy XAUUSD feed
 * (2 digits, 0.01 point, MetaQuotes-Demo at UTC+3), so component tests exercise
 * realistic shapes rather than convenient ones.
 */

import type {
  Candle,
  CandleSeries,
  ConnectionEventsResponse,
  HealthResponse,
  MarketSnapshot,
  Quote,
  Timeframe,
  TimeframeSummary,
} from '../types/market';
import type {
  BacktestReportDetail,
  BacktestReportRun,
  BacktestReports,
} from '../types/backtest';

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

export function makeSeries(timeframe: Timeframe = 'M15', count = 20): CandleSeries {
  const candles = Array.from({ length: count }, (_, index) =>
    makeCandle({
      time: 1_791_790_000 + index * 900,
      open: 4180 + index * 0.4,
      high: 4181 + index * 0.4,
      low: 4179 + index * 0.4,
      close: 4180.5 + index * 0.4,
      is_closed: index !== count - 1,
    }),
  );

  return {
    symbol: 'XAUUSD',
    timeframe,
    timeframe_seconds: 900,
    requested_limit: count,
    count,
    candles,
    latest_candle: candles[count - 1],
    latest_closed_candle: candles[count - 2],
    server_time_offset_seconds: BROKER_OFFSET_SECONDS,
    time_convention: 'broker_server_local',
    incomplete_history: false,
    warnings: [],
    generated_at: '2026-10-12T05:45:26.500Z',
  };
}

export function makeHealth(overrides: Partial<HealthResponse> = {}): HealthResponse {
  return {
    status: 'ok',
    app_name: 'Fibonacci MT5 Bot',
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

export function makeEvents(overrides: Partial<ConnectionEventsResponse> = {}): ConnectionEventsResponse {
  return {
    enabled: true,
    total_events: 3,
    total_snapshots: 1200,
    events: [],
    errors: [
      {
        timestamp: '2026-10-12T05:10:00.000Z',
        state: 'error',
        initialized: false,
        connected: false,
        account_type: 'demo',
        symbol: 'XAUUSD',
        error: 'MT5 initialization failed: -6 (Terminal: Authorization failed)',
       },
     ],
     ...overrides,
   };
}


/* ------------------------------------------------------------------ */
/* Read-only backtest report fixtures                                 */
/* ------------------------------------------------------------------ */

export function makeBacktestRun(overrides: Partial<BacktestReportRun> = {}): BacktestReportRun {
  return {
    run_id: 'xauusd_20260414_20261014_4eea7638',
    report_type: 'fibonacci_xauusd_backtest',
    generated_at_utc: '2026-10-14T04:07:35.735519+00:00',
    generated_at_ist: '2026-10-14T09:37:35.735519+05:30',
    symbol: 'XAUUSD',
    requested_start_utc: '2026-04-14T00:00:00+00:00',
    requested_end_utc: '2026-10-14T04:07:35.735519+00:00',
    timeframes: ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1'],
    timeframe_count: 7,
    strategy_fingerprint: '4eea76386812',
    output_dir: 'reports/backtests/xauusd_20260414_20261014_4eea7638',
    files: ['summary.json', 'M15.csv'],
    summary_available: true,
    ...overrides,
  };
}

export function makeBacktestReports(overrides: Partial<BacktestReports> = {}): BacktestReports {
  return {
    reports_root: 'reports/backtests',
    available: true,
    count: 1,
    read_only: true,
    trading_enabled: false,
    runs: [makeBacktestRun()],
    ...overrides,
  };
}

export function makeBacktestDetail(overrides: Partial<BacktestReportDetail> = {}): BacktestReportDetail {
  return {
    ...makeBacktestRun(),
    summary_file: 'summary.json',
    summary: {
      report_type: 'fibonacci_xauusd_backtest',
      data_source: 'MetaTrader5 desktop terminal',
      timeframes: [
        {
          timeframe: 'M15',
          status: 'evaluated',
          candle_count: 11510,
          confirmed_bullish: 31,
          confirmed_bearish: 45,
          trade_count: 46,
          profitability_established: true,
          error: null,
        },
      ],
    },
    ...overrides,
  };
}
