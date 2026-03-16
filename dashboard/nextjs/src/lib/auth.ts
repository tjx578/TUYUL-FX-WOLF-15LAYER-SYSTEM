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

/**
 * Build the Authorization header value.
 * Returns undefined when no token is stored so callers can omit the header.
 * Logs a loud error in production to surface missing auth config.
 */
export function bearerHeader(): string | undefined {
  const token = getTransportToken();
  if (token) {
    return `Bearer ${token}`;
  }

  if (typeof window !== "undefined" && process.env.NODE_ENV === "production") {
    console.error(
      "[auth] bearerHeader(): no JWT and no NEXT_PUBLIC_API_KEY. " +
      "All authenticated API calls will fail. " +
      "Set NEXT_PUBLIC_API_KEY in Vercel env vars or log in."
    );
  }

  return undefined;
}

/**
 * Token used for API/WS transports.
 * Prioritizes user JWT, then falls back to static API key for service-mode access.
 */
export function getTransportToken(): string | null {
  const jwt = getToken();
  if (jwt) {
    return jwt;
  }

  const apiKey = process.env.NEXT_PUBLIC_API_KEY?.trim();
  return apiKey || null;
}

