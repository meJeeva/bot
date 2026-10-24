import type { DailyPerformanceItem } from '../types/market';
import { formatSignedAmount } from '../services/format';
import { StateBlock } from './terminal/ui';

interface CumulativePnlChartProps {
  days: DailyPerformanceItem[];
  currency: string | null;
  timezone: string;
}

const WIDTH = 960;
const HEIGHT = 260;
const PADDING = { top: 14, right: 84, bottom: 26, left: 14 };

/**
 * Cumulative realized net P&L, one point per reporting day, built only from
 * the backend's daily rows. The line never invents a value for a day the
 * backend did not report, and the axes are labelled with the reporting
 * timezone and account currency.
 */
export function CumulativePnlChart({ days, currency, timezone }: CumulativePnlChartProps) {
  const ordered = [...days].sort((a, b) => a.date.localeCompare(b.date));

  if (ordered.length === 0) {
    return (
      <StateBlock
        title="No daily results to chart"
        detail="The cumulative curve appears once the backend reports daily rows for the range."
        testId="cumulative-empty"
      />
    );
  }

  const cumulative: number[] = [];
  let running = 0;
  for (const day of ordered) {
    running += day.net_pnl;
    cumulative.push(running);
  }

  let min = Math.min(0, ...cumulative);
  let max = Math.max(0, ...cumulative);
  if (max - min < 1e-9) {
    min -= 1;
    max += 1;
  }
  const pad = (max - min) * 0.12;
  min -= pad;
  max += pad;

  const plotWidth = WIDTH - PADDING.left - PADDING.right;
  const plotHeight = HEIGHT - PADDING.top - PADDING.bottom;
  const step = ordered.length > 1 ? plotWidth / (ordered.length - 1) : 0;
  const x = (index: number) => PADDING.left + index * step;
  const y = (value: number) => PADDING.top + ((max - value) / (max - min)) * plotHeight;

  const linePoints = cumulative
    .map((value, index) => `${x(index).toFixed(2)},${y(value).toFixed(2)}`)
    .join(' ');

  return (
    <div className="chart-frame" data-testid="cumulative-frame">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="chart-svg"
        role="img"
        aria-label={`Cumulative realized net P&L across ${ordered.length} days, ${currency ?? ''}, ${timezone}`}
        preserveAspectRatio="xMidYMid meet"
      >
        <line
          x1={PADDING.left}
          x2={WIDTH - PADDING.right}
          y1={y(0)}
          y2={y(0)}
          className="chart-level-line chart-level-reference"
        />
        <text x={WIDTH - PADDING.right + 6} y={y(0) + 3.5} className="chart-axis-label">
          0.00
        </text>

        {[max - pad, min + pad].map((edge) => (
          <g key={edge}>
            <line
              x1={PADDING.left}
              x2={WIDTH - PADDING.right}
              y1={y(edge)}
              y2={y(edge)}
              className="chart-grid"
            />
            <text x={WIDTH - PADDING.right + 6} y={y(edge) + 3.5} className="chart-axis-label">
              {edge.toFixed(0)}
            </text>
          </g>
        ))}

        <polyline points={linePoints} className="cumulative-line" fill="none" />

        {cumulative.map((value, index) => (
          <circle
            key={ordered[index].date}
            cx={x(index)}
            cy={y(value)}
            r={2.6}
            className={value >= 0 ? 'cumulative-dot cumulative-dot-up' : 'cumulative-dot cumulative-dot-down'}
          >
            <title>
              {ordered[index].date}: {formatSignedAmount(value)} {currency ?? ''}
            </title>
          </circle>
        ))}

        {ordered.length > 1 ? (
          <>
            <text x={x(0)} y={HEIGHT - 8} className="chart-axis-label chart-axis-time">
              {ordered[0].date}
            </text>
            <text
              x={x(Math.floor((ordered.length - 1) / 2))}
              y={HEIGHT - 8}
              className="chart-axis-label chart-axis-time"
            >
              {ordered[Math.floor((ordered.length - 1) / 2)].date}
            </text>
            <text
              x={x(ordered.length - 1)}
              y={HEIGHT - 8}
              className="chart-axis-label chart-axis-time"
            >
              {ordered[ordered.length - 1].date}
            </text>
          </>
        ) : (
          <text x={x(0)} y={HEIGHT - 8} className="chart-axis-label chart-axis-time">
            {ordered[0].date}
          </text>
        )}
      </svg>
      <p className="chart-legend-note" data-testid="cumulative-caption">
        Cumulative realized net P&L ({currency ?? 'account currency'}, {timezone}). Realized
        results only; floating P&L is reported separately.
      </p>
    </div>
  );
}
