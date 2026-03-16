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

// Track if we've already warned about missing auth to avoid console spam
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
 */
export async function fetchWsTicket(): Promise<string | null> {
  const jwt = getToken();
  if (jwt) return jwt;

  try {
    const res = await fetch("/api/auth/ws-ticket");
    if (!res.ok) return null;
    const data = await res.json() as { token?: string };
    return data.token ?? null;
  } catch {
    return null;
  }
}

