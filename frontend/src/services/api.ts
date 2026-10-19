/**
 * Typed REST client for the backend's read-only endpoints.
 *
 * Everything here is a GET: the dashboard observes market data and state and
 * never mutates the account. No endpoint in this application can place, modify
 * or close an order. The trading strategies have been removed, so there is no
 * strategy surface to query.
 */

import type {
  ApiErrorBody,
  CandleSeries,
  ConnectionEventsResponse,
  HealthResponse,
  MarketSnapshot,
  Quote,
  SymbolStatus,
  Timeframe,
} from '../types/market';
import type {
  ExecutionStatusOut,
  RiskStatusOut,
  ExecutionHistoryOut,
} from '../types/execution';
import type {
  BacktestReportDetail,
  BacktestReports,
} from '../types/backtest';

/** Empty by default so the Vite dev proxy handles routing (and CORS). */
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? '';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: unknown;

  constructor(status: number, code: string, message: string, detail: unknown = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

function isErrorBody(value: unknown): value is ApiErrorBody {
  return (
    typeof value === 'object' &&
    value !== null &&
    'error' in value &&
    typeof (value as ApiErrorBody).error?.message === 'string'
  );
}

export interface JsonRequestOptions {
  method?: 'GET' | 'POST' | 'DELETE';
  /** Serialised as JSON with a matching content type. */
  body?: unknown;
  signal?: AbortSignal;
}

/**
 * One JSON request against the backend, with the shared error envelope.
 *
 * Exported so the replay control client uses exactly the same transport,
 * timeout and error handling as the read-only endpoints.
 */
export async function requestJson<T>(
  path: string,
  options: JsonRequestOptions = {},
): Promise<T> {
  const { method = 'GET', body, signal } = options;
  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: {
        Accept: 'application/json',
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      ...(signal ? { signal } : {}),
    });
  } catch (cause) {
    throw new ApiError(0, 'network_error', `Cannot reach the backend at ${API_BASE_URL || '/'}.`, cause);
  }

  const text = await response.text();
  let payload: unknown = null;

  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    if (isErrorBody(payload)) {
      throw new ApiError(
        response.status,
        payload.error.code,
        payload.error.message,
        payload.error.detail,
      );
    }
    throw new ApiError(response.status, `http_${response.status}`, `Request failed (${response.status}).`);
  }

  return payload as T;
}

function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  return requestJson<T>(path, { signal });
}

export const api = {
  health: (signal?: AbortSignal) => request<HealthResponse>('/api/health', signal),

  mt5Status: (signal?: AbortSignal) =>
    request<{ status: MarketSnapshot['connection']; symbol: SymbolStatus }>(
      '/api/mt5/status',
      signal,
    ),

  quote: (signal?: AbortSignal) => request<Quote>('/api/market/quote', signal),

  snapshot: (signal?: AbortSignal) => request<MarketSnapshot>('/api/market/snapshot', signal),

  candles: (timeframe: Timeframe, limit = 300, signal?: AbortSignal) =>
    request<CandleSeries>(
      `/api/market/candles?timeframe=${encodeURIComponent(timeframe)}&limit=${limit}`,
      signal,
    ),

   mt5Events: (limit = 10, signal?: AbortSignal) =>
      request<ConnectionEventsResponse>(`/api/mt5/events?limit=${limit}`, signal),

  // Phase 4: read-only execution posture and risk state (never submits orders).
  executionStatus: (signal?: AbortSignal) =>
    request<ExecutionStatusOut>('/api/execution/status', signal),

  riskStatus: (signal?: AbortSignal) =>
    request<RiskStatusOut>('/api/execution/risk', signal),

  executionHistory: (signal?: AbortSignal) =>
    request<ExecutionHistoryOut>('/api/execution/history', signal),

  // Read-only historical report runs written by the CLI (never re-run).
  backtestReports: (signal?: AbortSignal) =>
    request<BacktestReports>('/api/reports', signal),

  backtestReport: (runId: string, signal?: AbortSignal) =>
    request<BacktestReportDetail>(
      `/api/reports/${encodeURIComponent(runId)}`,
      signal,
    ),
};

/** Direct download URL for one backtest report artifact. */
export function backtestReportFileUrl(runId: string, filename: string): string {
  return `${API_BASE_URL}/api/reports/${encodeURIComponent(runId)}/files/${encodeURIComponent(
    filename,
  )}`;
}

/** Human-readable message for any thrown value. */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}
