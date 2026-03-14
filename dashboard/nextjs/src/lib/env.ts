/**
 * Centralized env access.
 * NOTE: This file is now minimal since we use Next.js rewrites via next.config.js
 * to proxy all requests to the backend. The API_BASE_URL is resolved server-side
 * and never exposed to the browser.
 */

// Legacy export kept for backward compatibility — returns empty string
// since we no longer use a client-side base URL.
export const API_BASE_URL = "";

/**
 * Legacy validation function — now a no-op since all proxying is server-side.
 * Kept for backward compatibility with existing imports.
 */
export function validateEnv(): void {
  // No-op: env validation is now done in next.config.js
}

/**
 * Legacy function — returns empty string.
 * All API calls should use relative paths (e.g. /api/v1/...) which are
 * proxied by Next.js rewrites to the real backend via API_BASE_URL.
 * This function is kept for backward compatibility only.
 */
export function getApiBaseUrl(): string {
  return "";
}

/**
 * Legacy function — returns empty string.
 * WebSocket paths should use the relative /ws/... pattern.
 * The browser automatically converts http/https to ws/wss.
 * This function is kept for backward compatibility only.
 */
export function getWsBaseUrl(): string {
  return "";
}
