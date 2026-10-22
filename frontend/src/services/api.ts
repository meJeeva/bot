/**
 * Typed REST client for the backend's read-only market-data endpoints.
 *
 * Every request is a GET. There is no order, execution, strategy or backtest
 * surface: the trading strategies and execution pipeline have been removed, and
 * this client cannot mutate the account.
 */

import type {
  ApiErrorBody,
  HealthResponse,
  MarketSnapshot,
} from '../types/market';

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

/** One GET request against the backend, with the shared error envelope. */
async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
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

export const api = {
  health: (signal?: AbortSignal) => request<HealthResponse>('/api/health', signal),

  snapshot: (signal?: AbortSignal) => request<MarketSnapshot>('/api/market/snapshot', signal),
};

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
