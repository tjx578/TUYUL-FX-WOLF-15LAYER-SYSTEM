/**
 * Centralized env access.
 * NOTE: This file is now minimal since we use Next.js rewrites via next.config.js
 * to proxy all requests to the backend. The API_BASE_URL is resolved server-side
 * and never exposed to the browser.
 */

// Legacy export kept for existing imports — reads from NEXT_PUBLIC_API_BASE_URL.
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

const OPTIONAL_PUBLIC_VARS: string[] = [
  "NEXT_PUBLIC_API_BASE_URL",
  "NEXT_PUBLIC_WS_BASE_URL",
];

/**
 * Validates optional public environment variables at runtime.
 * These are no longer required — Next.js rewrites handle proxying.
 * Logs info (not warning) if they are set, for debugging purposes.
 */
export function validateEnv(): void {
  const set: string[] = [];
  for (const key of OPTIONAL_PUBLIC_VARS) {
    const val = process.env[key];
    if (val && val.trim() !== "") {
      set.push(`${key}=${val}`);
    }
  }
  if (set.length > 0) {
    console.info("[env] Public env overrides active:", set.join(", "));
  }
}

/**
 * Returns REST API base URL.
 *
 * With Next.js rewrites in place, the browser should use **relative paths**
 * (empty string base). The rewrites in next.config.js proxy /api/* to the
 * real backend. Only set NEXT_PUBLIC_API_BASE_URL when you intentionally
 * want the browser to call an absolute URL (e.g., local debugging).
 */
export function getApiBaseUrl(): string {
  const url =
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    process.env.NEXT_PUBLIC_API_URL;
  if (!url || url.trim() === "") {
    // Relative path — Next.js rewrites will proxy to backend
    return "";
  }
  return url.replace(/\/$/, ""); // strip trailing slash
}

/**
 * Returns WebSocket base URL.
 *
 * When NEXT_PUBLIC_WS_BASE_URL is not set, derive from the browser's
 * current origin so that http→ws and https→wss are correct automatically.
 * Next.js rewrites proxy /ws/* to the real backend.
 */
export function getWsBaseUrl(): string {
  const url = process.env.NEXT_PUBLIC_WS_BASE_URL;
  if (!url || url.trim() === "") {
    // Derive from current page origin (works in both dev and prod)
    if (typeof window !== "undefined") {
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      return `${proto}//${window.location.host}`;
    }
    // SSR fallback — won't actually be used for real WS connections
    return "";
  }
  return url.replace(/\/$/, ""); // strip trailing slash
}
