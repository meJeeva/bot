/**
 * Display formatting.
 *
 * The single most important rule here: an unavailable value renders as an
 * explicit placeholder, never as `0`. The backend reports missing prices as
 * `null` and the UI must not turn that into a number a trader might act on.
 */

export const UNAVAILABLE_GLYPH = '—';

export function isUsableNumber(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/** Format a price with the broker's digit count, or the placeholder. */
export function formatPrice(value: number | null | undefined, digits: number | null): string {
  if (!isUsableNumber(value)) {
    return UNAVAILABLE_GLYPH;
  }
  const places = isUsableNumber(digits) ? Math.max(0, Math.min(8, digits)) : 2;
  return value.toFixed(places);
}

/** Format a point count (whole points, no decimals unless needed). */
export function formatPoints(value: number | null | undefined): string {
  if (!isUsableNumber(value)) {
    return UNAVAILABLE_GLYPH;
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

/** Whole seconds as a compact human duration. */
export function formatDuration(seconds: number | null | undefined): string {
  if (!isUsableNumber(seconds)) {
    return UNAVAILABLE_GLYPH;
  }
  const rounded = Math.max(0, Math.round(seconds));
  if (rounded < 60) {
    return `${rounded}s`;
  }
  if (rounded < 3_600) {
    return `${Math.floor(rounded / 60)}m ${rounded % 60}s`;
  }
  return `${Math.floor(rounded / 3_600)}h ${Math.floor((rounded % 3_600) / 60)}m`;
}

/**
 * Timestamps are rendered in Indian Standard Time (IST, Asia/Kolkata).
 *
 * The application uses a single consistent timezone policy for all user-facing
 * displays: Asia/Kolkata (UTC+05:30) with the en-IN locale. This ensures the
 * same instant always renders the same way regardless of operator locale, and
 * matches the dashboard's timezone convention.
 *
 * Backend timestamps are preserved in their canonical format (timezone-aware UTC).
 * Display-time conversion happens exactly once at the UI boundary via these
 * formatters. No component should perform its own timezone conversion.
 */
const IST_LOCALE = 'en-IN';
const IST_TIME_ZONE = 'Asia/Kolkata';

/**
 * An ISO timestamp rendered as IST clock time, or the placeholder.
 * Uses 12-hour clock with uppercase AM/PM.
 */
export function formatTime(iso: string | null | undefined): string {
  if (!iso) {
    return UNAVAILABLE_GLYPH;
  }
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) {
    return UNAVAILABLE_GLYPH;
  }
  const formatted = parsed.toLocaleTimeString(IST_LOCALE, {
    timeZone: IST_TIME_ZONE,
    hour12: true,
  });
  return formatted.replace(/am/gi, 'AM').replace(/pm/gi, 'PM');
}

/** An ISO timestamp rendered as a IST date and time in DD/MM/YYYY, hh:mm:ss AM/PM IST format. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) {
    return UNAVAILABLE_GLYPH;
  }
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) {
    return UNAVAILABLE_GLYPH;
  }
  return parsed.toLocaleString(IST_LOCALE, {
    timeZone: IST_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  }) + ' IST';
}

/**
 * An ISO timestamp rendered as a UTC date and time, explicitly labelled UTC.
 *
 * Used for values the backend documents as true UTC (a tick instant, a bar
 * open time, a report's generation time). Rendering them in IST and calling
 * them UTC - or the reverse - would silently shift the instant.
 */
export function formatUtcDateTime(iso: string | null | undefined): string {
  if (!iso) {
    return UNAVAILABLE_GLYPH;
  }
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) {
    return UNAVAILABLE_GLYPH;
  }
  return (
    parsed.toLocaleString(IST_LOCALE, {
      timeZone: 'UTC',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: true,
    }) + ' UTC'
  );
}

/**
 * A broker-server wall clock reading, with no timezone conversion at all.
 *
 * MetaTrader tick and bar times are broker-server local time; the backend
 * carries them in a UTC-tagged field purely for transport. Converting them to
 * the operator's zone (or to IST) would invent an instant that does not exist
 * on the server, so this formatter reads the wall clock as-is. Always show it
 * next to a label naming the broker server.
 */
export function formatBrokerWallClock(iso: string | null | undefined): string {
  if (!iso) {
    return UNAVAILABLE_GLYPH;
  }
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) {
    return UNAVAILABLE_GLYPH;
  }
  return parsed.toLocaleTimeString(IST_LOCALE, {
    timeZone: 'UTC',
    hour12: true,
  }).replace(/am/gi, 'AM').replace(/pm/gi, 'PM');
}
