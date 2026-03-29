/**
 * Single source of truth for backend endpoint paths.
 *
 * All FE code that talks to the auth API must import paths from here
 * so a rename only requires one change instead of a multi-file grep.
 */

/** Auth session validation (GET). */
export const AUTH_SESSION = "/api/auth/session" as const;

/** Auth login — POST with { api_key } body, sets HttpOnly cookie. */
export const AUTH_LOGIN = "/api/auth/login" as const;

/** Auth logout — POST, clears HttpOnly cookie. */
export const AUTH_LOGOUT = "/api/auth/logout" as const;

/** Auth token refresh (POST). */
export const AUTH_REFRESH = "/api/auth/refresh" as const;
