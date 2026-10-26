import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { makeCandleSeries, makeQuote } from '../../test/fixtures';
import { PriceChart, type ChartLevel } from '../PriceChart';

const levels: ChartLevel[] = [
  { value: 4186.14, label: 'Reference', tone: 'reference' },
  { value: 4187.14, label: 'Buy entry (strategy)', tone: 'buy' },
  { value: 4100.0, label: 'Far away level', tone: 'stop' },
];

describe('PriceChart', () => {
  it('charts the candles the backend returned, nothing invented', () => {
    const series = makeCandleSeries();
    render(<PriceChart series={series} loading={false} error={null} quote={null} levels={[]} />);

    const frame = screen.getByTestId('chart-frame');
    expect(frame).toBeInTheDocument();
    expect(frame.querySelectorAll('.chart-candle').length).toBe(series.candles.length);
  });

  it('draws only the strategy levels that fall inside the charted range', () => {
    render(
      <PriceChart
        series={makeCandleSeries()}
        loading={false}
        error={null}
        quote={null}
        levels={levels}
      />,
    );

    const legendItems = screen.getAllByTestId('chart-legend-item');
    const legendText = legendItems.map((item) => item.textContent).join('\n');
    expect(legendText).toContain('Reference: 4186.14');
    expect(legendText).toContain('Buy entry');
    expect(legendText).not.toContain('Far away level');
  });

  it('shows the live bid as the current price line when a quote is present', () => {
    render(
      <PriceChart
        series={makeCandleSeries()}
        loading={false}
        error={null}
        quote={makeQuote({ bid: 4186.2 })}
        levels={[]}
      />,
    );

    expect(screen.getByTestId('chart-frame')).toBeInTheDocument();
  });

  it('never fabricates candles when the backend has none', () => {
    render(<PriceChart series={null} loading={false} error={null} quote={null} levels={levels} />);

    expect(screen.getByTestId('chart-empty')).toBeInTheDocument();
    expect(screen.queryByTestId('chart-frame')).not.toBeInTheDocument();
  });

  it('separates a transport error from an empty series', () => {
    const { unmount } = render(
      <PriceChart series={null} loading={false} error="Cannot reach the backend at /." quote={null} levels={[]} />,
    );
    expect(screen.getByTestId('chart-error')).toHaveTextContent('Candle history is unavailable');
    unmount();

    render(
      <PriceChart
        series={makeCandleSeries({ candles: [], latest_candle: null, latest_closed_candle: null, count: 0 })}
        loading={false}
        error={null}
        quote={null}
        levels={[]}
      />,
    );
    expect(screen.getByTestId('chart-empty')).toBeInTheDocument();
  });

  it('shows a loading state before the first candles arrive', () => {
    render(<PriceChart series={null} loading error={null} quote={null} levels={[]} />);

    expect(screen.getByTestId('chart-loading')).toBeInTheDocument();
  });
});
