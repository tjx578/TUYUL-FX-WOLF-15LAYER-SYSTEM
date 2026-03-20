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
 */
export class HttpError extends Error {
  status?: number;
  info?: unknown;

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
    throw new HttpError(
      `Request failed: ${res.status} ${res.statusText}`,
      res.status,
      info
    );
  }

  return res.json() as Promise<T>;
}
