/**
 * TUYUL FX Wolf-15 — Auth token management.
 *
 * Single source of truth for the JWT access token used by both
 * REST (Authorization: Bearer) and WebSocket (?token=<jwt>) transports.
 *
 * Storage: localStorage key "wolf15_token"  (browser-only, guard is built in)
 */

const TOKEN_KEY = "wolf15_token";

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
 */
export function bearerHeader(): string | undefined {
  const token = getToken();
  return token ? `Bearer ${token}` : undefined;
}
