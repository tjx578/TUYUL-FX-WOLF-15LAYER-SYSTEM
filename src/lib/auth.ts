/**
 * TUYUL FX Wolf-15 — Auth token management.
 *
 * Single source of truth for the JWT access token used by both
 * REST (Authorization: Bearer) and WebSocket (?token=<jwt>) transports.
 *
 * Storage policy:
 *   - Development: localStorage key "wolf15_token" (convenient for debugging).
 *   - Production: HttpOnly session cookie set via POST /api/set-session.
 *     getToken() returns null in production — callers should use fetchWsTicket()
 *     or server-side cookie auth instead of client-accessible localStorage.
 */

import type { UserRole } from "@/contracts/auth";

const TOKEN_KEY = "wolf15_token";

// True when running in a production Next.js build.
// process.env.NODE_ENV is statically inlined by the bundler.
const IS_PRODUCTION = process.env.NODE_ENV === "production";

export const ADMIN_ROLES = ["risk_admin", "config_admin", "approver"] as const;

export function hasRole(
  role: UserRole | undefined,
  allowedRoles: readonly UserRole[]
): boolean {
  if (!role) {
    return false;
  }
  return allowedRoles.includes(role);
}

/**
 * Retrieve the stored JWT.
 *
 * In production this always returns null — the JWT lives in an HttpOnly cookie
 * that is not accessible to client-side JavaScript.  Use fetchWsTicket() for
 * WebSocket auth or rely on credentials: "include" for REST calls.
 *
 * In development the token is read from localStorage for convenience.
 */
export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  if (IS_PRODUCTION) {
    // JWT must not be readable by JS in production (XSS mitigation).
    // Auth flows use the HttpOnly wolf15_session cookie instead.
    return null;
  }
  return localStorage.getItem(TOKEN_KEY);
}

/**
 * Persist a JWT (received from POST /api/v1/auth/login or equivalent).
 *
 * In production the token is persisted only via the HttpOnly cookie by
 * calling POST /api/set-session (best-effort, fire-and-forget).
 * localStorage is intentionally NOT written in production to prevent
 * XSS token theft.
 *
 * In development the token is written to localStorage for convenience.
 */
export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  if (IS_PRODUCTION) {
    // Persist via HttpOnly cookie only — do NOT write to localStorage in prod.
    fetch("/api/set-session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
      credentials: "include",
    }).catch((err: unknown) => {
      console.error("[auth] setToken: failed to persist session cookie via /api/set-session.", err);
    });
    return;
  }
  localStorage.setItem(TOKEN_KEY, token);
}

// ── WS ticket cache + in-flight deduplication ──────────────
// Declared here (above removeToken) so clearWsTicketCache() is defined
// before removeToken() calls it.
const WS_TICKET_CACHE_TTL_MS = 55_000;
let _wsTicketCache: { token: string; expiresAt: number } | null = null;
let _wsTicketInflight: Promise<string | null> | null = null;

/**
 * Invalidate the WS ticket cache (called on removeToken / logout).
 */
export function clearWsTicketCache(): void {
  _wsTicketCache = null;
  _wsTicketInflight = null;
}

/**
 * Remove the stored JWT (logout / session expiry).
 * Also clears the WS ticket cache so the next connect() fetches a fresh ticket.
 * In production the HttpOnly session cookie is cleared via a server call.
 */
export function removeToken(): void {
  if (typeof window === "undefined") return;
  // Always remove from localStorage (handles dev-mode and any legacy entries).
  localStorage.removeItem(TOKEN_KEY);
  clearWsTicketCache();
}

// Track if we've already warned about missing auth to avoid console spam.
// v2: switched to console.warn and single-fire guard 2026-03-16
let hasWarnedNoAuth = false;

/**
 * Build the Authorization header value.
 * Returns undefined when no token is stored so callers can omit the header.
 * Logs a single warning in development when no token is available.
 */
export function bearerHeader(): string | undefined {
  const token = getTransportToken();
  if (token) {
    hasWarnedNoAuth = false; // Reset so we warn again if token disappears
    return `Bearer ${token}`;
  }

  // Only warn once per session to avoid console spam on every fetch
  if (typeof window !== "undefined" && process.env.NODE_ENV === "development" && !hasWarnedNoAuth) {
    hasWarnedNoAuth = true;
    console.warn(
      "[auth] No JWT available — user not logged in. " +
      "REST calls use server middleware auth; direct client-to-backend calls may fail."
    );
  }

  return undefined;
}

/**
 * Token used for API/WS transports.
 * Returns the user JWT from localStorage, or null.
 *
 * NOTE: The static API key fallback (NEXT_PUBLIC_API_KEY) has been removed
 * to prevent leaking the key into the client JavaScript bundle.
 * For REST, Next.js middleware injects auth server-side.
 * For WebSocket, use fetchWsTicket() which calls a server route.
 */
export function getTransportToken(): string | null {
  return getToken();
}

/**
 * Fetch a WebSocket auth ticket from the server.
 * The server route reads the session cookie or the server-only API_KEY
 * env var — neither is exposed to the client bundle.
 *
 * Includes TTL cache + in-flight dedup to avoid hammering the server
 * during rapid WS reconnect cycles (root cause of 429 cascades).
 */
export async function fetchWsTicket(): Promise<string | null> {
  // 1. Short-circuit: stored JWT is the fastest path (no network call).
  const jwt = getToken();
  if (jwt) return jwt;

  // 2. Return cached ticket if still valid.
  if (_wsTicketCache && Date.now() < _wsTicketCache.expiresAt) {
    return _wsTicketCache.token;
  }

  // 3. Deduplicate: if a fetch is already in-flight, wait for it.
  if (_wsTicketInflight) {
    return _wsTicketInflight;
  }

  // 4. New fetch — set inflight guard immediately to prevent parallel calls.
  _wsTicketInflight = (async (): Promise<string | null> => {
    try {
      const res = await fetch("/api/auth/ws-ticket");
      if (res.status === 429) {
        if (process.env.NODE_ENV === "development") {
          console.warn("[auth] /api/auth/ws-ticket rate-limited (429). Using localStorage JWT.");
        }
        return null;
      }
      if (!res.ok) return null;
      const data = await res.json() as { token?: string };
      const token = data.token ?? null;
      if (token) {
        _wsTicketCache = { token, expiresAt: Date.now() + WS_TICKET_CACHE_TTL_MS };
      }
      return token;
    } catch {
      return null;
    } finally {
      _wsTicketInflight = null;
    }
  })();

  return _wsTicketInflight;
}

// ============================================
// JWT Auto-Refresh
// ============================================

const REFRESH_BUFFER_MS = 10 * 60 * 1000; // 10 minutes before expiry
let refreshTimerId: ReturnType<typeof setTimeout> | null = null;

/**
 * Decode JWT payload without a library (browser-safe).
 * Returns { exp, iat, sub, ... } or null if invalid.
 */
function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    const payload = JSON.parse(atob(parts[1]));
    return payload;
  } catch {
    return null;
  }
}

/**
 * Milliseconds until the token should be refreshed (expiry minus buffer).
 * Returns 0 if already expired or about to expire.
 */
function msUntilRefresh(token: string): number {
  const payload = decodeJwtPayload(token);
  if (!payload || typeof payload.exp !== "number") return 0;

  const expiresAtMs = payload.exp * 1000;
  const refreshAtMs = expiresAtMs - REFRESH_BUFFER_MS;
  const now = Date.now();

  return Math.max(0, refreshAtMs - now);
}

/**
 * Attempt token refresh via backend.
 * On success: update localStorage + session cookie + reschedule.
 * On failure: clear token + redirect to login.
 */
async function performRefresh(): Promise<void> {
  const currentToken = getToken();
  if (!currentToken) return;

  try {
    const res = await fetch("/api/auth/refresh", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${currentToken}`,
      },
      credentials: "include",
    });

    if (res.ok) {
      const data = await res.json() as { token?: string };
      if (data.token) {
        setToken(data.token);
        // Update session cookie (best-effort)
        await fetch("/api/set-session", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token: data.token }),
          credentials: "include",
        }).catch(() => { });
        scheduleRefresh(data.token);
        if (process.env.NODE_ENV === "development") {
          console.debug("[auth] Token refreshed, next refresh scheduled");
        }
      }
    } else {
      // Refresh failed — clear stale token but do NOT redirect.
      // Owner mode: dashboard is always accessible without a JWT.
      removeToken();
    }
  } catch {
    // Network error — retry in 30s
    refreshTimerId = setTimeout(performRefresh, 30_000);
  }
}

/**
 * Schedule auto-refresh based on token expiry.
 * Call after login success and after each refresh.
 */
export function scheduleRefresh(token?: string): void {
  if (typeof window === "undefined") return;

  if (refreshTimerId) {
    clearTimeout(refreshTimerId);
    refreshTimerId = null;
  }

  const t = token || getToken();
  if (!t) return;

  const waitMs = msUntilRefresh(t);

  if (waitMs <= 0) {
    // Token already expired or about to — refresh NOW
    performRefresh();
    return;
  }

  refreshTimerId = setTimeout(performRefresh, waitMs);

  if (process.env.NODE_ENV === "development") {
    console.debug(
      `[auth] Refresh scheduled in ${Math.round(waitMs / 60000)} min`
    );
  }
}

/**
 * Stop auto-refresh (call on logout).
 */
export function cancelRefresh(): void {
  if (refreshTimerId) {
    clearTimeout(refreshTimerId);
    refreshTimerId = null;
  }
}

