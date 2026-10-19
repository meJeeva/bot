import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useBacktestReports } from '../useBacktestReports';
import { api } from '../../services/api';
import { makeBacktestDetail, makeBacktestReports } from '../../test/fixtures';

vi.mock('../../services/api', () => ({
  api: {
    backtestReports: vi.fn(),
    backtestReport: vi.fn(),
  },
  describeError: (error: unknown) => (error instanceof Error ? error.message : String(error)),
}));

const mockedApi = vi.mocked(api);

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.backtestReports.mockResolvedValue(makeBacktestReports());
  mockedApi.backtestReport.mockResolvedValue(makeBacktestDetail());
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('useBacktestReports', () => {
  it('loads the run list and stops loading', async () => {
    const { result } = renderHook(() => useBacktestReports());

    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.reports?.count).toBe(1);
    expect(result.current.error).toBeNull();
  });

  it('loads a run detail after selecting it', async () => {
    const { result } = renderHook(() => useBacktestReports());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => result.current.selectRun('xauusd_20260414_20261014_4eea7638'));

    await waitFor(() => expect(result.current.detail).not.toBeNull());
    expect(mockedApi.backtestReport).toHaveBeenCalledWith(
      'xauusd_20260414_20261014_4eea7638',
      expect.anything(),
    );
    expect(result.current.detail?.summary).toBeDefined();
  });

  it('clears the detail when the selection is cleared', async () => {
    const { result } = renderHook(() => useBacktestReports());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => result.current.selectRun('xauusd_20260414_20261014_4eea7638'));
    await waitFor(() => expect(result.current.detail).not.toBeNull());

    act(() => result.current.selectRun(null));
    await waitFor(() => expect(result.current.detail).toBeNull());
  });

  it('surfaces a list failure without inventing runs', async () => {
    mockedApi.backtestReports.mockRejectedValue(new Error('backend down'));

    const { result } = renderHook(() => useBacktestReports());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBe('backend down');
    expect(result.current.reports).toBeNull();
  });
});
