import { formatDateTime, formatNumber } from '../services/format';
import { backtestReportFileUrl } from '../services/api';
import type { BacktestReportDetail, BacktestReports } from '../types/backtest';
import { backtestReportTypeLabel, readTimeframeRows } from '../types/backtest';

export interface BacktestReportsPanelProps {
  reports: BacktestReports | null;
  loading: boolean;
  error: string | null;
  selectedRunId: string | null;
  detail: BacktestReportDetail | null;
  detailLoading: boolean;
  detailError: string | null;
  onSelectRun: (runId: string | null) => void;
  onRefresh: () => void;
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : {};
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/**
 * Reports from previously run historical backtests.
 *
 * The backtest is a read-only CLI tool; this panel only reads the artifacts it
 * wrote, so runs are never overwritten or mixed. Everything here is a
 * historical simulation, never a live result or a broker trade.
 */
export function BacktestReportsPanel({
  reports,
  loading,
  error,
  selectedRunId,
  detail,
  detailLoading,
  detailError,
  onSelectRun,
  onRefresh,
}: BacktestReportsPanelProps) {
  return (
    <section className="card" aria-labelledby="backtest-heading">
      <header className="card-header">
        <h2 id="backtest-heading" data-testid="backtest-heading">
          Backtest reports
        </h2>
        <button type="button" className="button" onClick={onRefresh} disabled={loading}>
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </header>

      <p className="alert alert-warning" data-testid="backtest-disclaimer">
        Historical simulation only. Backtests are produced by the read-only command-line
        tool and written to disk as immutable runs; this panel never starts or overwrites a
        run. Results are not live prices and not broker performance.
      </p>

      {error ? (
        <p className="alert alert-error" data-testid="backtest-error">
          {error}
        </p>
      ) : null}

      {reports ? (
        <p className="footnote" data-testid="backtest-root">
          Reports root: <code>{reports.reports_root}</code>
        </p>
      ) : null}

      {loading && !reports ? (
        <p className="empty" data-testid="backtest-loading">
          Loading backtest reports…
        </p>
      ) : null}

      {reports && !reports.available ? (
        <p className="empty" data-testid="backtest-unavailable">
          No reports directory was found. Generate reports with{' '}
          <code>python -m app.backtest.cli --start YYYY-MM-DD --end YYYY-MM-DD</code> from the{' '}
          <code>backend</code> directory (or <code>scripts/run_backtest.ps1</code>).
        </p>
      ) : null}

      {reports && reports.available && reports.runs.length === 0 ? (
        <p className="empty" data-testid="backtest-empty">
          The reports directory is empty. Run the backtest CLI to create a report.
        </p>
      ) : null}

      {reports && reports.runs.length > 0 ? (
        <div className="table-responsive">
          <table className="strategy-table strategy-table-compact" data-testid="backtest-runs">
            <thead>
              <tr>
                <th>Run</th>
                <th>Type</th>
                <th>Generated (IST)</th>
                <th>Symbol</th>
                <th>Range (IST)</th>
                <th className="numeric">TFs</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {reports.runs.map((run) => (
                <tr key={run.run_id}>
                  <td className="mono-cell">{run.run_id}</td>
                  <td>{backtestReportTypeLabel(run.report_type)}</td>
                  <td>{formatDateTime(run.generated_at_utc)}</td>
                  <td>{run.symbol ?? '—'}</td>
                  <td>
                    {formatDateTime(run.requested_start_utc)} → {formatDateTime(run.requested_end_utc)}
                  </td>
                  <td className="numeric">{run.timeframe_count ?? run.timeframes.length}</td>
                  <td>
                    <button
                      type="button"
                      className="button"
                      data-testid={`backtest-view-${run.run_id}`}
                      onClick={() => onSelectRun(selectedRunId === run.run_id ? null : run.run_id)}
                    >
                      {selectedRunId === run.run_id ? 'Close' : 'View'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {selectedRunId ? (
        <BacktestRunDetail
          detail={detail}
          loading={detailLoading}
          error={detailError}
        />
      ) : null}
    </section>
  );
}

function BacktestRunDetail({
  detail,
  loading,
  error,
}: {
  detail: BacktestReportDetail | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading && !detail) {
    return <p className="empty" data-testid="backtest-detail-loading">Loading run detail…</p>;
  }
  if (error && !detail) {
    return (
      <p className="alert alert-error" data-testid="backtest-detail-error">
        {error}
      </p>
    );
  }
  if (!detail) {
    return null;
  }

  const summary = detail.summary;
  const costs = asRecord(summary?.transaction_costs);
  const riskPolicy = asRecord(summary?.risk_policy);
  const dataQuality = asRecord(summary?.data_quality);
  const method = asRecord(summary?.method);
  const rows = readTimeframeRows(summary);
  const dataSource = asString(summary?.data_source);

  return (
    <div className="backtest-detail" data-testid="backtest-detail">
      <div className="strategy-divider" />
      <h3>Run detail · {detail.run_id}</h3>

      <dl className="kv kv-compact">
        <div>
          <dt>Report type</dt>
          <dd>{backtestReportTypeLabel(detail.report_type)}</dd>
        </div>
        <div>
          <dt>Strategy fingerprint</dt>
          <dd>{detail.strategy_fingerprint ?? '—'}</dd>
        </div>
        <div>
          <dt>Symbol</dt>
          <dd>{detail.symbol ?? '—'}</dd>
        </div>
        <div>
          <dt>Requested range (IST)</dt>
          <dd>
            {formatDateTime(detail.requested_start_utc)} → {formatDateTime(detail.requested_end_utc)}
          </dd>
        </div>
        <div>
          <dt>Generated (IST)</dt>
          <dd>{formatDateTime(detail.generated_at_utc)}</dd>
        </div>
        <div>
          <dt>Timeframes</dt>
          <dd>{detail.timeframes.join(', ') || '—'}</dd>
        </div>
        {dataSource ? (
          <div>
            <dt>Data source</dt>
            <dd>{dataSource}</dd>
          </div>
        ) : null}
        {asString(method.replay) ? (
          <div>
            <dt>Method</dt>
            <dd>{asString(method.replay)}</dd>
          </div>
        ) : null}
        {asString(costs.model) ? (
          <div>
            <dt>Transaction costs</dt>
            <dd>
              {asString(costs.model)}
              {asNumber(costs.central_cost_price) !== null
                ? ` · central ${formatNumber(asNumber(costs.central_cost_price))}`
                : ''}
            </dd>
          </div>
        ) : null}
        {riskPolicy.cost_allowance_percent !== undefined ? (
          <div>
            <dt>Cost allowance</dt>
            <dd>{String(riskPolicy.cost_allowance_percent)}%</dd>
          </div>
        ) : null}
      </dl>

      {Object.keys(dataQuality).length > 0 ? (
        <>
          <h4>Dataset coverage</h4>
          <table className="strategy-table strategy-table-compact" data-testid="backtest-coverage">
            <thead>
              <tr>
                <th>TF</th>
                <th className="numeric">Bars</th>
                <th>Coverage</th>
                <th>First bar (IST)</th>
                <th>Last bar (IST)</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(dataQuality).map(([timeframe, raw]) => {
                const entry = asRecord(raw);
                return (
                  <tr key={timeframe}>
                    <td>{timeframe}</td>
                    <td className="numeric">{asNumber(entry.candle_count) ?? '—'}</td>
                    <td>{entry.coverage_complete ? 'complete' : 'incomplete'}</td>
                    <td>{formatDateTime(asString(entry.first_candle_utc))}</td>
                    <td>{formatDateTime(asString(entry.last_candle_utc))}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      ) : null}

      {rows.length > 0 ? (
        <>
          <h4>Per-timeframe results</h4>
          <div className="table-responsive">
            <table className="strategy-table strategy-table-compact" data-testid="backtest-timeframes">
              <thead>
                <tr>
                  <th>TF</th>
                  <th>Status</th>
                  <th className="numeric">Bars</th>
                  <th className="numeric">Conf. buy</th>
                  <th className="numeric">Conf. sell</th>
                  <th className="numeric">Trades</th>
                  <th>Profitability</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.timeframe}>
                    <td>{row.timeframe}</td>
                    <td>{row.status ?? '—'}</td>
                    <td className="numeric">{row.candle_count ?? '—'}</td>
                    <td className="numeric">{row.confirmed_bullish ?? '—'}</td>
                    <td className="numeric">{row.confirmed_bearish ?? '—'}</td>
                    <td className="numeric">{row.trade_count ?? '—'}</td>
                    <td>
                      {row.profitability_established === true
                        ? 'established'
                        : row.profitability_established === false
                          ? 'not established'
                          : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      <h4>Artifacts</h4>
      <ul className="artifact-list" data-testid="backtest-artifacts">
        {detail.files.map((file) => (
          <li key={file}>
            <a
              className="link-button"
              href={backtestReportFileUrl(detail.run_id, file)}
              target="_blank"
              rel="noreferrer"
            >
              {file}
            </a>
          </li>
        ))}
      </ul>
      <p className="footnote">
        Files are served read-only from <code>{detail.output_dir}</code>. Previous runs are never
        overwritten.
      </p>
    </div>
  );
}
