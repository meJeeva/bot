/**
 * Types mirroring the read-only backtest-report schemas in
 * `app/schemas/backtest.py`.
 *
 * These describe reports that were produced earlier by the backtest CLI. They
 * are historical simulations and must never be presented as live results or as
 * broker performance.
 */

export interface BacktestReportRun {
  run_id: string;
  report_type: string;
  generated_at_utc: string | null;
  generated_at_ist: string | null;
  symbol: string | null;
  requested_start_utc: string | null;
  requested_end_utc: string | null;
  timeframes: string[];
  timeframe_count: number | null;
  strategy_fingerprint: string | null;
  output_dir: string;
  files: string[];
  summary_available: boolean;
}

export interface BacktestReports {
  reports_root: string;
  available: boolean;
  count: number;
  read_only: boolean;
  trading_enabled: boolean;
  runs: BacktestReportRun[];
}

export interface BacktestReportDetail extends BacktestReportRun {
  summary_file: string | null;
  summary: Record<string, unknown> | null;
}

/** One row of a per-timeframe backtest summary. */
export interface BacktestTimeframeRow {
  timeframe: string;
  status?: string;
  candle_count?: number;
  confirmed_bullish?: number;
  confirmed_bearish?: number;
  trade_count?: number | null;
  profitability_established?: boolean | null;
  error?: string | null;
}

export const BACKTEST_REPORT_TYPE_LABELS: Record<string, string> = {
  fibonacci_xauusd_backtest: 'Per-timeframe backtest',
  fibonacci_exit_policy_comparison: 'Exit-policy comparison',
  full_strategy_backtest: 'Full-strategy backtest',
};

export function backtestReportTypeLabel(reportType: string): string {
  return BACKTEST_REPORT_TYPE_LABELS[reportType] ?? reportType;
}

/** Read the per-timeframe rows out of a raw summary, defensively. */
export function readTimeframeRows(summary: Record<string, unknown> | null): BacktestTimeframeRow[] {
  if (!summary) return [];
  const rows = summary.timeframes;
  if (!Array.isArray(rows)) return [];
  return rows.filter(
    (row): row is BacktestTimeframeRow =>
      typeof row === 'object' && row !== null && typeof (row as BacktestTimeframeRow).timeframe === 'string',
  );
}
