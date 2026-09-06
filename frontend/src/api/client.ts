/**
 * The single door between the app and the API.
 *
 * Everything that talks to the backend goes through here, so spec 002 gets one
 * place to add the CSRF header and the 401 -> refresh -> retry interceptor
 * rather than sprinkling auth through every component.
 */

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
}

/**
 * An API failure carrying the backend's stable machine-readable code.
 *
 * Callers should branch on `code`, never on `message` — messages are prose and
 * will be rewritten during the Phase 3 personality pass.
 */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;
  readonly requestId: string | null;

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> = {},
    requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

const API_BASE = "/api";
const CSRF_COOKIE = "ctf_csrf";
const CSRF_HEADER = "X-CSRF-Token";

export interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  /** Internal: stops a failed refresh from retrying itself forever. */
  skipRefresh?: boolean;
}

function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match?.[1] ? decodeURIComponent(match[1]) : null;
}

/**
 * Refreshes are deduplicated: a page that fires five requests at once when the
 * access token has just expired must not start five rotations, because rotation
 * invalidates the previous token and four of them would be treated as replay —
 * which revokes the whole session as a theft signal.
 */
let refreshInFlight: Promise<boolean> | null = null;

async function refreshSession(): Promise<boolean> {
  refreshInFlight ??= (async () => {
    try {
      await request<unknown>("/auth/refresh", { method: "POST", skipRefresh: true });
      return true;
    } catch {
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, headers, skipRefresh, ...rest } = options;
  const method = (rest.method ?? "GET").toUpperCase();
  const csrfToken = readCookie(CSRF_COOKIE);
  const needsCsrf = !["GET", "HEAD", "OPTIONS"].includes(method);

  const response = await fetch(`${API_BASE}${path}`, {
    ...rest,
    // Sessions are httpOnly cookies (spec 002); without this they are not sent.
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      ...(needsCsrf && csrfToken ? { [CSRF_HEADER]: csrfToken } : {}),
      ...headers,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  const requestId = response.headers.get("X-Request-ID");

  if (response.status === 401 && !skipRefresh) {
    // The 15-minute access token has probably just expired. Rotate once and
    // replay; if the refresh itself fails, the original 401 stands.
    if (await refreshSession()) {
      return request<T>(path, { ...options, skipRefresh: true });
    }
  }

  if (!response.ok) {
    throw await toApiError(response, requestId);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

async function toApiError(response: Response, requestId: string | null): Promise<ApiError> {
  try {
    const body = (await response.json()) as ApiErrorBody;
    if (body?.error?.code) {
      return new ApiError(
        response.status,
        body.error.code,
        body.error.message,
        body.error.details ?? {},
        requestId,
      );
    }
  } catch {
    // A proxy or ingress failure will not be JSON. Fall through.
  }

  return new ApiError(
    response.status,
    "unexpected_response",
    "The server returned an unreadable response.",
    {},
    requestId,
  );
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "POST", body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "PATCH", body }),
  delete: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "DELETE" }),
};
