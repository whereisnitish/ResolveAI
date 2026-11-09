/**
 * Typed client for the ResolveAI REST API.
 *
 * - Same-origin requests to /api/v1 (proxied to Django by Next rewrites).
 * - Session auth via HttpOnly cookie; CSRF token echoed in X-CSRFToken.
 * - Errors are normalized into ApiError using the backend's error envelope.
 */

const API_BASE = "/api/v1";
const CSRF_COOKIE = "resolveai_csrftoken";
const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export type FieldErrors = Record<string, string[] | string>;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  readonly requestId?: string;

  constructor(status: number, code: string, message: string, details?: unknown, requestId?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }

  get isUnauthenticated(): boolean {
    return this.status === 401 || (this.status === 403 && this.code === "not_authenticated");
  }

  /** Field-level validation messages, flattened to one string per field. */
  get fieldErrors(): Record<string, string> {
    if (!this.details || typeof this.details !== "object" || Array.isArray(this.details)) return {};
    const out: Record<string, string> = {};
    for (const [field, value] of Object.entries(this.details as FieldErrors)) {
      out[field] = Array.isArray(value) ? String(value[0]) : String(value);
    }
    return out;
  }
}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.split("; ").find((row) => row.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.split("=")[1]) : null;
}

let csrfPromise: Promise<string> | null = null;

async function ensureCsrfToken(): Promise<string> {
  const existing = readCookie(CSRF_COOKIE);
  if (existing) return existing;
  csrfPromise ??= fetch(`${API_BASE}/auth/csrf/`, { credentials: "same-origin" })
    .then((r) => r.json() as Promise<{ csrf_token: string }>)
    .then((body) => body.csrf_token)
    .finally(() => {
      csrfPromise = null;
    });
  return csrfPromise;
}

type Query = Record<string, string | number | boolean | undefined | null>;

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Query;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: Query): string {
  const clean = path.replace(/^\/+/, "").replace(/\/?$/, "/");
  const url = `${API_BASE}/${clean}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  const isForm = typeof FormData !== "undefined" && options.body instanceof FormData;
  if (options.body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  if (UNSAFE_METHODS.has(method)) headers["X-CSRFToken"] = await ensureCsrfToken();

  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), {
      method,
      headers,
      credentials: "same-origin",
      body: isForm ? (options.body as FormData) : options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "network_error", "Unable to reach the server. Check your connection and try again.");
  }

  if (response.status === 204) return undefined as T;

  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const envelope = (payload as { error?: { code?: string; message?: string; details?: unknown; request_id?: string } })
      ?.error;
    throw new ApiError(
      response.status,
      envelope?.code ?? "error",
      envelope?.message ?? `Request failed (${response.status}).`,
      envelope?.details,
      envelope?.request_id,
    );
  }
  return payload as T;
}

export const api = {
  get: <T>(path: string, query?: Query) => apiRequest<T>(path, { query }),
  post: <T>(path: string, body?: unknown) => apiRequest<T>(path, { method: "POST", body: body ?? {} }),
  patch: <T>(path: string, body: unknown) => apiRequest<T>(path, { method: "PATCH", body }),
  delete: <T = void>(path: string) => apiRequest<T>(path, { method: "DELETE" }),
  /** multipart/form-data POST (browser sets the boundary). */
  upload: <T>(path: string, form: FormData) => apiRequest<T>(path, { method: "POST", body: form }),
  /** GET a URL returned by the API (e.g. cursor pagination `next`), kept same-origin. */
  getUrl: <T>(absoluteUrl: string) => {
    const url = new URL(absoluteUrl, window.location.origin);
    return apiRequest<T>(url.pathname.replace(/^\/api\/v1\//, ""), {
      query: Object.fromEntries(url.searchParams.entries()),
    });
  },
};
