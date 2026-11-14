import { getSupabase, isSupabaseConfigured } from '@/lib/supabase';

// All business data flows through FastAPI (§6.1). The Supabase access token is sent as Bearer.
const configuredBase: string | undefined = import.meta.env.VITE_API_BASE_URL;

function resolveDefaultApiBase(): string {
  if (configuredBase && configuredBase.length > 0) return configuredBase;
  if (
    typeof window !== 'undefined' &&
    window.location.hostname &&
    window.location.hostname !== 'localhost' &&
    window.location.hostname !== '127.0.0.1'
  ) {
    return `http://${window.location.hostname}:8000`;
  }
  return 'http://localhost:8000';
}

export const API_BASE_URL: string = resolveDefaultApiBase();

/** The standard error envelope {error:{code,message,details,request_id}} as a JS error. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  readonly requestId: string | null;

  constructor(
    status: number,
    code: string,
    message: string,
    details: unknown,
    requestId: string | null,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }

  /** Field errors from FORM_VALIDATION_FAILED: {field_key: [messages]}. */
  get fieldErrors(): Record<string, string[]> {
    if (this.details && typeof this.details === 'object' && !Array.isArray(this.details)) {
      const out: Record<string, string[]> = {};
      for (const [k, v] of Object.entries(this.details as Record<string, unknown>)) {
        if (Array.isArray(v)) out[k] = v.map(String);
      }
      return out;
    }
    return {};
  }
}

export interface ApiRequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  query?: Record<string, string | number | boolean | string[] | null | undefined>;
  idempotencyKey?: string;
  signal?: AbortSignal;
}

async function accessToken(): Promise<string | null> {
  if (!isSupabaseConfigured()) return null;
  const { data } = await getSupabase().auth.getSession();
  return data.session?.access_token ?? null;
}

function buildUrl(path: string, query?: ApiRequestOptions['query']): string {
  const url = new URL(`${API_BASE_URL}/api/v1${path}`);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === null || value === undefined || value === '') continue;
    if (Array.isArray(value)) {
      for (const v of value) url.searchParams.append(key, v);
    } else {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

/** The standard error envelope of a failed response (falls back to the HTTP status text). */
async function errorFromResponse(res: Response): Promise<ApiError> {
  let code = `HTTP_${String(res.status)}`;
  let message = res.statusText || 'Request failed';
  let details: unknown = null;
  let rid = res.headers.get('X-Request-ID');
  try {
    const body = (await res.json()) as {
      error?: { code?: string; message?: string; details?: unknown; request_id?: string };
    };
    if (body.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      details = body.error.details ?? null;
      rid = body.error.request_id ?? rid;
    }
  } catch {
    // Non-JSON error body (e.g. a proxy page): keep the HTTP status text.
  }
  return new ApiError(res.status, code, message, details, rid);
}

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  const token = await accessToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (options.idempotencyKey) headers['Idempotency-Key'] = options.idempotencyKey;

  let res: Response;
  try {
    res = await fetch(buildUrl(path, options.query), {
      method: options.method ?? 'GET',
      headers,
      body: options.body === undefined ? null : JSON.stringify(options.body),
      signal: options.signal ?? null,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err;
    throw new ApiError(
      0,
      'NETWORK_ERROR',
      'Cannot reach the RMS API. Check your connection.',
      null,
      null,
    );
  }

  if (!res.ok) throw await errorFromResponse(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** GET a file (e.g. a CSV export) with the session token and hand it to the browser. */
export async function apiDownload(
  path: string,
  query: ApiRequestOptions['query'],
  filename: string,
): Promise<void> {
  const headers: Record<string, string> = {};
  const token = await accessToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(buildUrl(path, query), { headers });
  } catch {
    throw new ApiError(
      0,
      'NETWORK_ERROR',
      'Cannot reach the RMS API. Check your connection.',
      null,
      null,
    );
  }
  if (!res.ok) throw await errorFromResponse(res);
  const url = URL.createObjectURL(await res.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err;
  return new ApiError(
    0,
    'CLIENT_ERROR',
    err instanceof Error ? err.message : String(err),
    null,
    null,
  );
}

export function newIdempotencyKey(): string {
  return `web-${crypto.randomUUID()}`;
}
