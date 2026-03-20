/**
 * apiFetch — canonical authenticated REST fetcher.
 *
 * Attaches  Authorization: Bearer <token>  on every request.
 * Use this instead of bare fetch() throughout the dashboard.
 *
 * Usage:
 *   import { apiFetch } from "@/lib/fetcher";
 *   const data = await apiFetch("/api/v1/verdict/all");
 *
 * Note: Uses relative paths (no base URL) so Next.js rewrites proxy to the real backend.
 */
import { bearerHeader } from "@/lib/auth";

/**
 * Typed fetch error — carries HTTP status so callers (SWR retry, diagnostic panels)
 * can distinguish auth failures (401/403) from network errors.
 * `retryAfterMs` is populated for 429 responses from the `Retry-After` header.
 */
export class HttpError extends Error {
  status?: number;
  info?: unknown;
  retryAfterMs?: number;

  constructor(message: string, status?: number, info?: unknown) {
    super(message);
    this.name = "HttpError";
    this.status = status;
    this.info = info;
  }
}

export async function apiFetch(
  path: string,
  opts: RequestInit = {}
): Promise<Response> {
  // Relative path — Next.js rewrites proxy /api/* to the backend.
  const auth = bearerHeader();

  return fetch(path, {
    ...opts,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(auth ? { Authorization: auth } : {}),
      ...(opts.headers as Record<string, string> | undefined),
    },
  });
}

/**
 * SWR-compatible fetcher (GET + Bearer token).
 * Pass to useSWR as the second argument.
 * Throws HttpError with status code for proper error differentiation.
 */
export async function swrFetcher<T = unknown>(url: string): Promise<T> {
  const res = await apiFetch(url);

  if (!res.ok) {
    let info: unknown = null;
    try {
      info = await res.json();
    } catch {
      try {
        info = await res.text();
      } catch {
        info = null;
      }
    }
    const error = new HttpError(
      `Request failed: ${res.status} ${res.statusText}`,
      res.status,
      info
    );
    if (res.status === 429) {
      const retryAfter = res.headers.get("Retry-After");
      if (retryAfter) {
        // Retry-After can be a delay-seconds integer or an HTTP-date string (RFC 7231)
        const parsed = parseInt(retryAfter, 10);
        error.retryAfterMs = !isNaN(parsed)
          ? parsed * 1000
          : Math.max(0, new Date(retryAfter).getTime() - Date.now());
      } else {
        error.retryAfterMs = 60_000; // default: 60s when no header is present
      }
    }
    throw error;
  }

  return res.json() as Promise<T>;
}
