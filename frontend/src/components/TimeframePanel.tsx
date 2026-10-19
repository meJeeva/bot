import { formatDateTime, formatPoints, formatPrice, formatVolume } from '../services/format';
import { TIMEFRAMES, type Candle, type Timeframe, type TimeframeSummary } from '../types/market';
import { CandleChart } from './CandleChart';
import { ValueOrUnavailable } from './ValueOrUnavailable';

export interface TimeframePanelProps {
  timeframe: Timeframe;
  onTimeframeChange: (timeframe: Timeframe) => void;
  summaries: Record<string, TimeframeSummary>;
  summary: TimeframeSummary | null;
  candles: Candle[];
  loading: boolean;
  error: string | null;
  symbol: string | null;
  onRefresh: () => void;
}

/**
 * Timeframe selector plus the latest bar and candlestick chart.
 *
 * All seven timeframes are selectable. The "latest closed" and "forming" bars
 * are shown separately because the newest bar is still changing and must never
 * be presented as a finished bar.
 */
export function TimeframePanel({
  timeframe,
  onTimeframeChange,
  summaries,
  summary,
  candles,
  loading,
  error,
  symbol,
  onRefresh,
}: TimeframePanelProps) {
  const digits = summary?.latest_closed
    ? inferDigits(summary.latest_closed)
    : candles.length > 0
      ? inferDigits(candles[candles.length - 1])
      : 2;

  return (
    <section className="card card-wide" aria-labelledby="timeframe-heading">
      <header className="card-header">
        <h2 id="timeframe-heading">Timeframes</h2>
        <button type="button" className="button" onClick={onRefresh}>
          Refresh history
        </button>
      </header>

      <div className="timeframe-tabs" role="tablist" aria-label="Timeframe">
        {TIMEFRAMES.map((name) => {
          const item = summaries[name];
          const selected = name === timeframe;
          return (
            <button
              key={name}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-label={`Timeframe ${name}`}
              className={selected ? 'tab tab-active' : 'tab'}
              onClick={() => onTimeframeChange(name)}
              title={item?.error ?? undefined}
            >
              {name}
              <span className="tab-sub">
                {item?.latest_closed ? item.latest_closed.close.toFixed(digits) : '—'}
              </span>
            </button>
          );
        })}
      </div>

      {error ? (
        <p className="alert alert-error" data-testid="candles-error">
          {error}
        </p>
      ) : null}

      <div className="candle-summary">
        <div>
          <span className="quote-label">Latest closed ({timeframe})</span>
          <CandleRow candle={summary?.latest_closed ?? null} digits={digits} testId="latest-closed" />
        </div>
        <div>
          <span className="quote-label">Forming bar</span>
          <CandleRow candle={summary?.forming ?? null} digits={digits} testId="forming" />
        </div>
      </div>

      {loading && candles.length === 0 ? (
        <p className="empty" data-testid="chart-loading">
          Loading {timeframe} history...
        </p>
      ) : null}

      {!loading && candles.length === 0 && !error ? (
        <p className="empty" data-testid="chart-empty">
          No candle data is available for {timeframe}.
        </p>
      ) : null}

      <CandleChart candles={candles} symbol={symbol} timeframe={timeframe} />

      <p className="footnote">
        Showing {candles.length} of {summary?.candle_count ?? candles.length} cached bars. Chart times
        are UTC; the broker server runs at a measured offset from UTC.
      </p>
    </section>
  );
}

function CandleRow({
  candle,
  digits,
  testId,
}: {
  candle: Candle | null;
  digits: number;
  testId: string;
}) {
  if (!candle) {
    return (
      <p className="empty" data-testid={`${testId}-empty`}>
        Not available yet.
      </p>
    );
  }

  return (
    <dl className="kv kv-inline" data-testid={testId}>
      <div>
        <dt>Time</dt>
        <dd>{formatDateTime(candle.open_time_utc)}</dd>
      </div>
      <div>
        <dt>O</dt>
        <dd>{formatPrice(candle.open, digits)}</dd>
      </div>
      <div>
        <dt>H</dt>
        <dd>{formatPrice(candle.high, digits)}</dd>
      </div>
      <div>
        <dt>L</dt>
        <dd>{formatPrice(candle.low, digits)}</dd>
      </div>
      <div>
        <dt>C</dt>
        <dd>{formatPrice(candle.close, digits)}</dd>
      </div>
      <div>
        <dt>Vol</dt>
        <dd>{formatVolume(candle.tick_volume)}</dd>
      </div>
      <div>
        <dt>Spread</dt>
        <dd>
          <ValueOrUnavailable value={formatPoints(candle.spread_points)} raw={candle.spread_points} /> points
        </dd>
      </div>
    </dl>
  );
}

/** Infer the display precision from the prices the broker returned. */
function inferDigits(candle: Candle): number {
  const sample = candle.close || candle.open;
  const text = String(sample);
  const dot = text.indexOf('.');
  return dot >= 0 ? text.length - dot - 1 : 0;
}
