import { describe, expect, it } from 'vitest';

import {
  formatBrokerWallClock,
  formatDateTime,
  formatUtcDateTime,
} from '../format';

describe('timestamp formatting states its clock', () => {
  it('renders a true UTC instant in UTC and labels it', () => {
    const rendered = formatUtcDateTime('2026-10-12T05:45:26.000Z');

    expect(rendered).toContain('12/10/2026');
    expect(rendered).toContain('05:45:26');
    expect(rendered.endsWith('UTC')).toBe(true);
  });

  it('renders a broker wall clock without shifting it', () => {
    // The server clock reads 08:45:26 at UTC+3; converting it to IST would
    // claim 14:15:26, which is neither the server's time nor the tick's UTC.
    const rendered = formatBrokerWallClock('2026-10-12T08:45:26.000Z');

    expect(rendered).toContain('8:45:26');
    expect(rendered).not.toContain('14:15');
  });

  it('keeps the IST display convention for ordinary timestamps', () => {
    // 05:45:26 UTC is 11:15:26 IST.
    const rendered = formatDateTime('2026-10-12T05:45:26.000Z');

    expect(rendered).toContain('11:15:26');
    expect(rendered.endsWith('IST')).toBe(true);
  });

  it('renders an unavailable timestamp as the placeholder', () => {
    expect(formatUtcDateTime(null)).toBe('—');
    expect(formatBrokerWallClock(undefined)).toBe('—');
  });
});
