/**
 * TUYUL FX Wolf-15 — Auth token management.
 *
 * Single source of truth for the JWT access token used by both
 * REST (Authorization: Bearer) and WebSocket (?token=<jwt>) transports.
 *
 * Storage: localStorage key "wolf15_token"  (browser-only, guard is built in)
 */

import type { UserRole } from "@/contracts/auth";

const TOKEN_KEY = "wolf15_token";

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
 * Retrieve the stored JWT.  Returns null if not set or called server-side.
 */
export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

/**
 * Persist a JWT (received from POST /api/v1/auth/login or equivalent).
 */
export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(TOKEN_KEY, token);
}

/**
 * Remove the stored JWT (logout / session expiry).
 */
export function removeToken(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
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

// ─── WS Ticket Cache ─────────────────────────────────────────────────────────
// Tickets are valid ~30 min; we cache for 4 min to stay well within that window
// while avoiding stampedes on every reconnect attempt.
let _ticketCache: { token: string; expiresAt: number } | null = null;
let _ticketPromise: Promise<string | null> | null = null;
const TICKET_CACHE_TTL_MS = 4 * 60 * 1000; // 4 min

/**
 * Invalidate the cached WS ticket.
 * Call on logout or when a 401 is received on the WS connection.
 */
export function clearWsTicketCache(): void {
  _ticketCache = null;
  _ticketPromise = null;
}

/**
 * Fetch a WebSocket auth ticket from the server.
 * The server route reads the session cookie or the server-only API_KEY
 * env var — neither is exposed to the client bundle.
 *
 * Caching: tickets are cached for 4 min and concurrent calls share the same
 * in-flight Promise so a burst of reconnect attempts never fans into multiple
 * /api/auth/ws-ticket requests.
 * Includes TTL cache + in-flight dedup to avoid hammering the server
 * during rapid WS reconnect cycles (root cause of 429 cascades).
 */
export async function fetchWsTicket(): Promise<string | null> {
  const jwt = getToken();
  if (jwt) return jwt;

  // Return cached ticket if still valid
  if (_ticketCache && Date.now() < _ticketCache.expiresAt) {
    return _ticketCache.token;
  }

  // Deduplicate concurrent requests — return the in-flight promise if one exists
  // Dedup: if an in-flight request exists, await the same promise
  if (_ticketPromise) return _ticketPromise;

  _ticketPromise = (async () => {
    try {
      const res = await fetch("/api/auth/ws-ticket");
      if (!res.ok) return null;
      const data = await res.json() as { token?: string };
      const token = data.token ?? null;
      if (token) {
        _ticketCache = { token, expiresAt: Date.now() + TICKET_CACHE_TTL_MS };
      }
      return token;
    } catch {
      return null;
    } finally {
      _ticketPromise = null;
    }
  })();

  return _ticketPromise;
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
      // Refresh failed — token invalid or expired
      removeToken();
      if (typeof window !== "undefined") {
        window.location.href = "/login";
      }
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

