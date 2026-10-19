/// <reference types="vitest/globals" />
import '@testing-library/jest-dom/vitest';

/**
 * jsdom does not implement ResizeObserver, which the charting library uses for
 * its auto-sizing mode. A no-op implementation keeps component tests focused on
 * behaviour rather than on layout.
 */
if (typeof globalThis.ResizeObserver === 'undefined') {
  class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }

  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
}

// jsdom has no layout engine; the chart uses this for its initial size.
if (typeof window !== 'undefined' && !window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}
