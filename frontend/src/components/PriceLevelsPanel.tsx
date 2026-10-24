import type { AutoTradingStatus } from '../types/market';
import { formatDateTime, isUsableNumber } from '../services/format';
import { ValueOrUnavailable } from './ValueOrUnavailable';

interface PriceLevelsPanelProps {
  status: AutoTradingStatus | null;
  /** Broker digit count used to format prices (from symbol metadata). */
  digits: number | null;
}

/**
 * Every price level of the current cycle, grouped by where the value comes
 * from:
 *
 * * **Strategy-calculated** - the level the formula produced (reference,
 *   entries, initial stops, trailing/favorable extremes).
 * * **Submitted to broker** - the pending order tickets the cycle armed.
 * * **Broker-filled / reported** - the position ticket, fill price and time
 *   the backend read back from MT5, plus the break-even level it reports.
 *
 * The panel never claims a calculated level was accepted by the broker: only
 * tickets and fill data live in the confirmed group.
 */
export function PriceLevelsPanel({ status, digits }: PriceLevelsPanelProps) {
  if (status === null) {
    return (
      <section className="card" aria-labelledby="levels-heading">
        <header className="card-header">
          <h2 id="levels-heading">Cycle price levels</h2>
        </header>
        <p className="empty" data-testid="levels-empty">
          Auto-trading status is not available yet, so no cycle levels can be shown.
        </p>
      </section>
    );
  }

  const hasCycle =
    isUsableNumber(status.reference_value) &&
    (isUsableNumber(status.buy_entry) || isUsableNumber(status.sell_entry));

  return (
    <section className="card" aria-labelledby="levels-heading">
      <header className="card-header">
        <h2 id="levels-heading">Cycle price levels</h2>
        <span className="levels-side" data-testid="levels-active-side">
          {status.active_side ? `active: ${status.active_side}` : 'no active side'}
        </span>
      </header>

      {!hasCycle ? (
        <p className="empty" data-testid="levels-no-cycle">
          No cycle levels have been calculated yet. Levels appear once the worker builds a cycle.
        </p>
      ) : (
        <div className="levels-groups">
          <div className="levels-group">
            <h3 className="levels-group-title" data-testid="levels-strategy-title">
              Strategy-calculated
            </h3>
            <dl className="levels-list">
              <LevelRow
                label="Reference price"
                tone="reference"
                value={status.reference_value}
                digits={digits}
                testId="level-reference"
              />
              <LevelRow
                label="Buy Stop entry"
                tone="buy"
                value={status.buy_entry}
                digits={digits}
                testId="level-buy-entry"
              />
              <LevelRow
                label="Buy initial SL"
                tone="stop"
                value={status.buy_sl}
                digits={digits}
                testId="level-buy-sl"
              />
              <LevelRow
                label="Sell Stop entry"
                tone="sell"
                value={status.sell_entry}
                digits={digits}
                testId="level-sell-entry"
              />
              <LevelRow
                label="Sell initial SL"
                tone="stop"
                value={status.sell_sl}
                digits={digits}
                testId="level-sell-sl"
              />
              <LevelRow
                label="Highest favorable (buy)"
                tone="neutral"
                value={status.highest_favorable_price}
                digits={digits}
                testId="level-high-water"
              />
              <LevelRow
                label="Lowest favorable (sell)"
                tone="neutral"
                value={status.lowest_favorable_price}
                digits={digits}
                testId="level-low-water"
              />
            </dl>
          </div>

          <div className="levels-group">
            <h3 className="levels-group-title" data-testid="levels-submitted-title">
              Submitted to broker
            </h3>
            <dl className="levels-list">
              <TicketRow
                label="Buy Stop ticket"
                ticket={status.buy_order_ticket}
                testId="level-buy-ticket"
              />
              <TicketRow
                label="Sell Stop ticket"
                ticket={status.sell_order_ticket}
                testId="level-sell-ticket"
              />
            </dl>
          </div>

          <div className="levels-group">
            <h3 className="levels-group-title" data-testid="levels-confirmed-title">
              Broker-filled / reported
            </h3>
            <dl className="levels-list">
              <TextRow
                label="Position ticket"
                tone="neutral"
                value={status.position_ticket != null ? `#${status.position_ticket}` : null}
                testId="level-position-ticket"
              />
              <LevelRow
                label="Entry price (fill)"
                tone="buy"
                value={status.entry_price}
                digits={digits}
                testId="level-entry-price"
              />
              <TextRow
                label="Entry time"
                tone="neutral"
                value={formatDateTime(status.entry_time)}
                testId="level-entry-time"
              />
              <TextRow
                label="Break-even level"
                tone={status.break_even_active ? 'protect' : 'neutral'}
                value={price(status.break_even_level, digits)}
                raw={status.break_even_level ?? null}
                testId="level-break-even"
                suffix={status.break_even_active ? 'active' : 'not active'}
              />
              <TextRow
                label="Last processed deal"
                tone="neutral"
                value={
                  status.last_processed_deal !== null &&
                  status.last_processed_deal !== undefined
                    ? String(status.last_processed_deal)
                    : null
                }
                testId="level-last-deal"
              />
              <TextRow
                label="Previous cycle complete"
                tone="neutral"
                value={status.previous_cycle_complete ? 'yes' : null}
                testId="level-previous-cycle"
              />
            </dl>
          </div>
        </div>
      )}
    </section>
  );
}

type LevelTone = 'reference' | 'buy' | 'sell' | 'stop' | 'protect' | 'neutral';

function price(value: number | null | undefined, digits: number | null): string | null {
  if (!isUsableNumber(value)) {
    return null;
  }
  const places = isUsableNumber(digits) ? Math.max(0, Math.min(8, digits)) : 2;
  return value.toFixed(places);
}

interface LevelRowProps {
  label: string;
  tone: LevelTone;
  value: number | null | undefined;
  digits: number | null;
  testId: string;
}

/** A row whose value is a price number, formatted with the broker's digits. */
function LevelRow({ label, tone, value, digits, testId }: LevelRowProps) {
  return (
    <div className={`level-row level-${tone}`}>
      <dt>{label}</dt>
      <dd data-testid={testId}>
        <ValueOrUnavailable value={price(value, digits)} raw={value ?? null} />
      </dd>
    </div>
  );
}

interface TextRowProps {
  label: string;
  tone: LevelTone;
  value: string | null;
  raw?: number | null;
  suffix?: string;
  testId: string;
}

/** A row whose value is already display text (ids, timestamps, flags). */
function TextRow({ label, tone, value, raw, suffix, testId }: TextRowProps) {
  return (
    <div className={`level-row level-${tone}`}>
      <dt>{label}</dt>
      <dd data-testid={testId}>
        <ValueOrUnavailable value={value} raw={raw} />
        {suffix ? <span className="value-suffix">{suffix}</span> : null}
      </dd>
    </div>
  );
}

function TicketRow({
  label,
  ticket,
  testId,
}: {
  label: string;
  ticket: number | null | undefined;
  testId: string;
}) {
  return (
    <div className="level-row level-ticket">
      <dt>{label}</dt>
      <dd data-testid={testId}>
        <ValueOrUnavailable
          value={ticket != null ? `#${ticket}` : null}
          raw={ticket ?? null}
          title="No pending order ticket was reported for this side"
        />
      </dd>
    </div>
  );
}
