import type { CandleSeries, Quote } from '../types/market';
import { isUsableNumber } from '../services/format';
import { StateBlock } from './terminal/ui';

export interface ChartLevel {
  value: number | null | undefined;
  label: string;
  tone: 'reference' | 'buy' | 'sell' | 'stop' | 'protect' | 'live';
}

interface PriceChartProps {
  series: CandleSeries | null;
  loading: boolean;
  error: string | null;
  quote: Quote | null;
  levels: ChartLevel[];
}

const WIDTH = 960;
const HEIGHT = 340;
const PADDING = { top: 10, right: 92, bottom: 26, left: 10 };

/**
 * Candlestick chart over the backend's existing candle endpoint.
 *
 * Presentation only: the series, the live bid line and the strategy level
 * overlays all come from data the backend already publishes. Level lines are
 * drawn from the cycle's *calculated* levels and labelled as such - a line on
 * this chart never implies a broker-accepted order; submitted tickets live in
 * the cycle price-levels panel.
 */
export function PriceChart({ series, loading, error, quote, levels }: PriceChartProps) {
  const candles = series?.candles ?? [];

  if (error && candles.length === 0) {    return (
      <section className="card chart-card" aria-labelledby="chart-heading">
        <ChartHeader series={series} />
        <StateBlock
          title="Candle history is unavailable"
          detail={error}
          tone="error"
          testId="chart-error"
        />
      </section>
    );
  }

  if (loading && candles.length === 0) {
    return (
      <section className="card chart-card" aria-labelledby="chart-heading">
        <ChartHeader series={series} />
        <StateBlock title="Loading candle history…" testId="chart-loading" />
      </section>
    );
  }

  if (candles.length === 0) {
    return (
      <section className="card chart-card" aria-labelledby="chart-heading">
        <ChartHeader series={series} />
        <StateBlock
          title="No candles to chart"
          detail="The backend has not returned candle history for this timeframe yet."
          testId="chart-empty"
        />
      </section>
    );
  }

  let min = Math.min(...candles.map((candle) => candle.low));
  let max = Math.max(...candles.map((candle) => candle.high));
  if (max - min < 1e-9) {
    min -= 0.5;
    max += 0.5;
  }
  const pad = (max - min) * 0.08;
  min -= pad;
  max += pad;

  const plotWidth = WIDTH - PADDING.left - PADDING.right;
  const plotHeight = HEIGHT - PADDING.top - PADDING.bottom;
  const step = plotWidth / candles.length;
  const bodyWidth = Math.max(1.5, step * 0.62);

  const x = (index: number) => PADDING.left + index * step + step / 2;
  const y = (price: number) => PADDING.top + ((max - price) / (max - min)) * plotHeight;

  const lastCandle = candles[candles.length - 1];
  const livePrice = isUsableNumber(quote?.bid)
    ? (quote.bid as number)
    : isUsableNumber(lastCandle.close)
      ? lastCandle.close
      : null;

  const drawnLevels = levels
    .filter((level) => isUsableNumber(level.value))
    .map((level) => ({ ...level, value: level.value as number }))
    .filter((level) => level.value >= min && level.value <= max);

  const gridPrices = gridLines(min, max);

  return (
    <section className="card chart-card" aria-labelledby="chart-heading">
      <ChartHeader series={series} />
      <div className="chart-frame" data-testid="chart-frame">
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="chart-svg"
          role="img"
          aria-label={`Candlestick chart, ${series?.timeframe ?? ''} ${series?.symbol ?? ''}, ${candles.length} bars`}
          preserveAspectRatio="xMidYMid meet"
        >
          {gridPrices.map((price) => (
            <g key={price}>
              <line
                x1={PADDING.left}
                x2={WIDTH - PADDING.right}
                y1={y(price)}
                y2={y(price)}
                className="chart-grid"
              />
              <text x={WIDTH - PADDING.right + 6} y={y(price) + 3.5} className="chart-axis-label">
                {price.toFixed(2)}
              </text>
            </g>
          ))}

          {candles.map((candle, index) => {
            const up = candle.close >= candle.open;
            const bodyTop = y(Math.max(candle.open, candle.close));
            const bodyBottom = y(Math.min(candle.open, candle.close));
            return (
              <g
                key={candle.time}
                className={up ? 'chart-candle chart-candle-up' : 'chart-candle chart-candle-down'}
              >
                <line
                  x1={x(index)}
                  x2={x(index)}
                  y1={y(candle.high)}
                  y2={y(candle.low)}
                  className="chart-wick"
                />
                <rect
                  x={x(index) - bodyWidth / 2}
                  y={bodyTop}
                  width={bodyWidth}
                  height={Math.max(1, bodyBottom - bodyTop)}
                  className="chart-body"
                  opacity={candle.is_closed ? 1 : 0.55}
                />
              </g>
            );
          })}

          {drawnLevels.map((level) => (
            <g key={level.label} className={`chart-level chart-level-${level.tone}`}>
              <line
                x1={PADDING.left}
                x2={WIDTH - PADDING.right}
                y1={y(level.value)}
                y2={y(level.value)}
                className="chart-level-line"
              />
              <text x={WIDTH - PADDING.right + 6} y={y(level.value) + 3.5} className="chart-level-label">
                {shortLabel(level.label)}
              </text>
            </g>
          ))}

          {livePrice !== null ? (
            <g className="chart-level chart-level-live">
              <line
                x1={PADDING.left}
                x2={WIDTH - PADDING.right}
                y1={y(livePrice)}
                y2={y(livePrice)}
                className="chart-level-line"
              />
              <text x={WIDTH - PADDING.right + 6} y={y(livePrice) + 3.5} className="chart-level-label">
                {livePrice.toFixed(2)}
              </text>
            </g>
          ) : null}

          {candles.length > 1 ? (
            <>
              <text x={x(0)} y={HEIGHT - 8} className="chart-axis-label chart-axis-time">
                {axisTime(candles[0])}
              </text>
              <text
                x={x(Math.floor((candles.length - 1) / 2))}
                y={HEIGHT - 8}
                className="chart-axis-label chart-axis-time"
              >
                {axisTime(candles[Math.floor((candles.length - 1) / 2)])}
              </text>
              <text x={x(candles.length - 1)} y={HEIGHT - 8} className="chart-axis-label chart-axis-time">
                {axisTime(lastCandle)}
              </text>
            </>
          ) : null}
        </svg>
      </div>

      <ul className="chart-legend" data-testid="chart-legend">
        {drawnLevels.map((level) => (
          <li
            key={level.label}
            className={`chart-legend-item chart-level-${level.tone}`}
            data-testid="chart-legend-item"
          >
            <span className="chart-legend-swatch" aria-hidden="true" />
            {level.label}: {level.value.toFixed(2)}
          </li>
        ))}
        <li className="chart-legend-item chart-legend-note">
          Level lines are strategy-calculated; submitted tickets are listed in the cycle levels
          panel. Times are UTC (broker clock offset noted in Connection).
        </li>
      </ul>
    </section>
  );
}

function ChartHeader({ series }: { series: CandleSeries | null }) {
  return (
    <header className="card-header">
      <h2 id="chart-heading">
        Price chart
        {series ? ` · ${series.symbol} ${series.timeframe}` : ''}
      </h2>
      {series && series.warnings.length > 0 ? (
        <span className="badge badge-stale" data-testid="chart-warnings">
          {series.warnings.length} warning{series.warnings.length === 1 ? '' : 's'}
        </span>
      ) : null}
    </header>
  );
}

/** ~5 evenly spaced, human-friendly horizontal grid prices. */
function gridLines(min: number, max: number): number[] {
  const rawStep = (max - min) / 5;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const niceSteps = [1, 2, 2.5, 5, 10];
  const step = niceSteps.map((m) => m * magnitude).find((candidate) => candidate >= rawStep) ?? rawStep;
  const first = Math.ceil(min / step) * step;
  const lines: number[] = [];
  for (let value = first; value <= max; value += step) {
    lines.push(Number(value.toFixed(6)));
  }
  return lines;
}

function shortLabel(label: string): string {
  const cut = label.indexOf(' (');
  return (cut === -1 ? label : label.slice(0, cut)).slice(0, 14);
}

function axisTime(candle: { open_time_utc: string }): string {
  const parsed = new Date(candle.open_time_utc);
  if (Number.isNaN(parsed.getTime())) {
    return '';
  }
  return `${String(parsed.getUTCHours()).padStart(2, '0')}:${String(
    parsed.getUTCMinutes(),
  ).padStart(2, '0')}`;
}
