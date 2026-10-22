import {
  formatBrokerWallClock,
  formatDuration,
  formatPoints,
  formatPrice,
  formatUtcDateTime,
} from '../services/format';
import type { Quote } from '../types/market';
import { ValueOrUnavailable } from './ValueOrUnavailable';

interface QuotePanelProps {
  quote: Quote | null;
}

/**
 * Live bid / ask / spread for the selected symbol.
 *
 * Every numeric cell goes through `ValueOrUnavailable`, so a price the terminal
 * could not supply shows as "unavailable" rather than as `0.00`.
 */
export function QuotePanel({ quote }: QuotePanelProps) {
  const freshness = quote?.freshness ?? 'unknown';

  return (
    <section className="card" aria-labelledby="quote-heading">
      <header className="card-header">
        <h2 id="quote-heading">
          Live quote{quote ? ` · ${quote.symbol}` : ''}
        </h2>
        <span className={`badge badge-${freshness}`} data-testid="quote-freshness">
          {freshness}
        </span>
      </header>

      {quote === null ? (
        <p className="empty" data-testid="quote-empty">
          No tick has been received from MetaTrader 5 yet.
        </p>
      ) : (
        <>
          <div className="quote-grid">
            <div className="quote-cell">
              <span className="quote-label">Bid</span>
              <span className="quote-price bid" data-testid="quote-bid">
                <ValueOrUnavailable value={formatPrice(quote.bid, quote.digits)} raw={quote.bid} />
              </span>
            </div>

            <div className="quote-cell">
              <span className="quote-label">Ask</span>
              <span className="quote-price ask" data-testid="quote-ask">
                <ValueOrUnavailable value={formatPrice(quote.ask, quote.digits)} raw={quote.ask} />
              </span>
            </div>

            <div className="quote-cell">
              <span className="quote-label">Spread</span>
              <span className="quote-price" data-testid="quote-spread">
                <ValueOrUnavailable
                  value={formatPrice(quote.spread_price, quote.digits)}
                  raw={quote.spread_price}
                />
                <span className="quote-sub" data-testid="quote-spread-points">
                  {formatPoints(quote.spread_points)} points
                </span>
              </span>
            </div>

            <div className="quote-cell">
              <span className="quote-label">Last</span>
              <span className="quote-price">
                <ValueOrUnavailable value={formatPrice(quote.last, quote.digits)} raw={quote.last} />
              </span>
            </div>
          </div>

          <dl className="kv kv-compact">
            <div>
              <dt>Tick time (UTC)</dt>
              <dd data-testid="quote-tick-time">{formatUtcDateTime(quote.tick_time_utc)}</dd>
            </div>
            <div>
              <dt>Broker server time</dt>
              <dd data-testid="quote-tick-broker">
                {formatBrokerWallClock(quote.tick_time_broker)}
              </dd>
            </div>
            <div>
              <dt>Age</dt>
              <dd data-testid="quote-age">{formatDuration(quote.age_seconds)}</dd>
            </div>
            <div>
              <dt>Digits</dt>
              <dd data-testid="quote-digits">{quote.digits}</dd>
            </div>
            <div>
              <dt>Point</dt>
              <dd data-testid="quote-point">{quote.point}</dd>
            </div>
            <div>
              <dt>Tick size / value</dt>
              <dd>
                {quote.tick_size ?? '—'} / {quote.tick_value ?? '—'}
              </dd>
            </div>
          </dl>
        </>
      )}
    </section>
  );
}
