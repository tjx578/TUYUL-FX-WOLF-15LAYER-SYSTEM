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

export async function apiFetch(
  path: string,
  opts: RequestInit = {}
): Promise<Response> {
  // Relative path — Next.js rewrites proxy /api/* to the backend.
  const auth = bearerHeader();

  return fetch(path, {
    ...opts,
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
 */
export async function swrFetcher<T = unknown>(url: string): Promise<T> {
  const res = await apiFetch(url);
  if (!res.ok) {
    throw new Error(`Failed to fetch ${url}: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}
