import { UNAVAILABLE_GLYPH, isUsableNumber } from '../services/format';

interface ValueOrUnavailableProps {
  /** The formatted value; `null` or an empty string means unavailable. */
  value: string | null;
  /** Optional raw value used to decide whether the datum exists. */
  raw?: number | null | undefined;
  suffix?: string;
  title?: string;
}

/**
 * Renders a value, or an explicit "unavailable" placeholder.
 *
 * The dashboard must never present a missing price as `0` or as the last known
 * number without saying so, so this component is the single place that decides
 * how an absent value looks.
 */
export function ValueOrUnavailable({ value, raw, suffix, title }: ValueOrUnavailableProps) {
  const hasRaw = raw === undefined ? true : isUsableNumber(raw);
  const hasValue = value !== null && value !== '' && value !== UNAVAILABLE_GLYPH;
  const available = hasRaw && hasValue;

  if (!available) {
    return (
      <span className="value value-unavailable" title={title ?? 'Not provided by the terminal'}>
        {UNAVAILABLE_GLYPH}
        <span className="sr-only"> unavailable</span>
      </span>
    );
  }

  return (
    <span className="value" title={title}>
      {value}
      {suffix ? <span className="value-suffix">{suffix}</span> : null}
    </span>
  );
}
