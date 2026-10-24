import type {
  ApiErrorBody,
  HealthResponse,
  MarketSnapshot,
  CandleSeries,
  AutoTradingStatus,
  AutoTradingHistoryResponse,
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

interface RequestOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
}

/** One request against the backend, with the shared error envelope. */
async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET';
  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: { Accept: 'application/json', ...(options.body ? { 'Content-Type': 'application/json' } : {}) },
      ...(options.body ? { body: JSON.stringify(options.body) } : {}),
      ...(options.signal ? { signal: options.signal } : {}),
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
  health: (signal?: AbortSignal) => request<HealthResponse>('/api/health', { signal }),

  snapshot: (signal?: AbortSignal) => request<MarketSnapshot>('/api/market/snapshot', { signal }),

  candles: (
    timeframe: string,
    limit: number,
    signal?: AbortSignal,
  ) =>
    request<CandleSeries>(
      `/api/market/candles?timeframe=${encodeURIComponent(timeframe)}&limit=${limit}`,
      { signal },
    ),

  autoTrading: {
    start: () => request<AutoTradingStatus>('/api/auto-trading/start', { method: 'POST' }),
    stop: () => request<AutoTradingStatus>('/api/auto-trading/stop', { method: 'POST' }),
    status: (signal?: AbortSignal) => request<AutoTradingStatus>('/api/auto-trading/status', { signal }),
    history: (signal?: AbortSignal) =>
      request<AutoTradingHistoryResponse>('/api/auto-trading/history', { signal }),
  },
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
