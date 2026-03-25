import { bearerHeader } from "@/lib/auth";

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

export async function apiFetch(path: string, opts: RequestInit = {}): Promise<Response> {
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

export async function swrFetcher<T = unknown>(url: string): Promise<T> {
  const res = await apiFetch(url);
  if (!res.ok) {
    let info: unknown = null;
    try { info = await res.json(); } catch { try { info = await res.text(); } catch { info = null; } }
    const error = new HttpError(`Request failed: ${res.status} ${res.statusText}`, res.status, info);
    if (res.status === 429) {
      const retryAfterHeader = res.headers.get("Retry-After");
      error.retryAfterMs = retryAfterHeader ? Number(retryAfterHeader) * 1000 : 60_000;
    }
    throw error;
  }
  return res.json() as Promise<T>;
}
