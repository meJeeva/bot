import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { makeQuote } from '../../test/fixtures';
import { QuotePanel } from '../QuotePanel';

describe('QuotePanel', () => {
  it('shows the live bid and ask with the broker digit count', () => {
    render(<QuotePanel quote={makeQuote()} />);

    expect(screen.getByTestId('quote-bid')).toHaveTextContent('4185.58');
    expect(screen.getByTestId('quote-ask')).toHaveTextContent('4186.14');
    expect(screen.getByTestId('quote-freshness')).toHaveTextContent('live');
  });

  it('shows the spread in price units and in points', () => {
    render(<QuotePanel quote={makeQuote()} />);

    expect(screen.getByTestId('quote-spread')).toHaveTextContent('0.56');
    expect(screen.getByTestId('quote-spread-points')).toHaveTextContent('56 points');
  });

  it('shows digits and point size', () => {
    render(<QuotePanel quote={makeQuote()} />);

    expect(screen.getByTestId('quote-digits')).toHaveTextContent('2');
    expect(screen.getByTestId('quote-point')).toHaveTextContent('0.01');
  });

  it('renders an unavailable bid as a placeholder, never as zero', () => {
    render(<QuotePanel quote={makeQuote({ bid: null })} />);

    const bid = screen.getByTestId('quote-bid');
    expect(bid).toHaveTextContent('—');
    expect(bid).not.toHaveTextContent('0.00');
    expect(bid).not.toHaveTextContent('4185');
  });

  it('renders an unavailable ask as a placeholder', () => {
    render(<QuotePanel quote={makeQuote({ ask: null, spread_price: null, spread_points: null })} />);

    expect(screen.getByTestId('quote-ask')).toHaveTextContent('—');
    expect(screen.getByTestId('quote-spread')).toHaveTextContent('—');
  });

  it('renders a zero "last" as unavailable rather than as a real price', () => {
    // MetaTrader returns 0.0 when the broker publishes no last price.
    render(<QuotePanel quote={makeQuote({ last: 0 })} />);

    const panel = screen.getByTestId('quote-spread').closest('.card');
    expect(panel).not.toBeNull();
  });

  it('shows a stale badge when the tick is stale', () => {
    render(<QuotePanel quote={makeQuote({ freshness: 'stale', is_stale: true })} />);

    expect(screen.getByTestId('quote-freshness')).toHaveTextContent('stale');
  });

  it('explains the absence of data when no tick has arrived', () => {
    render(<QuotePanel quote={null} />);

    expect(screen.getByTestId('quote-empty')).toHaveTextContent(
      'No tick has been received from MetaTrader 5 yet.',
    );
  });

  it('shows the tick age and timestamp', () => {
    render(<QuotePanel quote={makeQuote({ age_seconds: 12.4 })} />);

    expect(screen.getByTestId('quote-age')).toHaveTextContent('12s');
    expect(screen.getByTestId('quote-tick-time')).not.toHaveTextContent('—');
  });

  it('shows an unavailable age when the tick time is unknown', () => {
    render(<QuotePanel quote={makeQuote({ age_seconds: null, freshness: 'unknown' })} />);

    expect(screen.getByTestId('quote-age')).toHaveTextContent('—');
  });
});
