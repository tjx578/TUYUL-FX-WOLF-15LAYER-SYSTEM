/**
 * TUYUL FX Wolf-15 — Environment Resolution
 *
 * Single source of truth for all env-derived config.
 *
 * Deployment rules:
 *   REST  → relative path  → Next.js rewrite /api/* proxies to backend (safe on Vercel)
 *   WS    → MUST be direct  → Vercel cannot upgrade WebSocket connections.
 *           Set NEXT_PUBLIC_WS_BASE_URL to the Railway/backend wss:// origin.
 *
 * Env vars in use (exactly these two, nothing else):
 *   NEXT_PUBLIC_API_BASE_URL   optional  override REST base (default: relative via rewrite)
 *   NEXT_PUBLIC_WS_BASE_URL    required  bare wss:// ORIGIN for Railway — NO /ws suffix!
 *
 * REMOVED (do NOT use):
 *   NEXT_PUBLIC_WS_URL         was in wsService.ts (deleted) — never set this
 *   NEXT_PUBLIC_API_URL        legacy alias — use NEXT_PUBLIC_API_BASE_URL
 */

/**
 * Returns the REST API base URL.
 *
 * Default: empty string (relative) — Next.js rewrite /api/* handles proxying.
 * Override with NEXT_PUBLIC_API_BASE_URL for direct backend calls (dev/debug).
 */
export function getApiBaseUrl(): string {
  const apiBaseRaw = process.env.NEXT_PUBLIC_API_BASE_URL;
  const apiLegacyRaw = process.env.NEXT_PUBLIC_API_URL; // legacy alias, still tolerated
  const url = typeof apiBaseRaw === "string" && apiBaseRaw.trim() !== ""
    ? apiBaseRaw
    : apiLegacyRaw;
  const normalized = typeof url === "string" ? url.trim() : "";
  if (normalized.length === 0) {
    return ""; // relative — rewrite in next.config.js handles the proxy
  }
  return normalized.replace(/\/$/, "");
}

/**
 * Returns the WebSocket base URL.
 *
 * On Vercel: NEXT_PUBLIC_WS_BASE_URL MUST be set to the Railway wss:// URL.
 * Vercel serverless functions cannot handle WebSocket upgrades — /ws/* rewrites
 * in next.config.js are for local-dev only (via Next.js dev server proxy).
 *
 * Fallback (local dev only): derives ws:// or wss:// from window.location.host.
 * This will work in local dev where Next.js dev server proxies /ws/*.
 * It will NOT work on Vercel without the env var.
 */
export function getWsBaseUrl(): string {
  const wsBaseRaw = process.env.NEXT_PUBLIC_WS_BASE_URL;
  const url = typeof wsBaseRaw === "string" ? wsBaseRaw.trim() : "";
  if (url.length === 0) {
    if (typeof window !== "undefined") {
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      if (
        process.env.NODE_ENV === "development" &&
        (window.location.hostname.includes("vercel") ||
          window.location.hostname.includes(".app"))
      ) {
        console.warn(
          "[env] WARNING: NEXT_PUBLIC_WS_BASE_URL is not set in a production-like environment. " +
          "WebSocket connections will fail. " +
          "Set NEXT_PUBLIC_WS_BASE_URL=wss://your-api.up.railway.app (bare origin, NO /ws suffix) in your Vercel project."
        );
      }
      return `${proto}//${window.location.host}`;
    }
    return ""; // SSR fallback — not used for real connections
  }
  // Strip trailing slash AND accidental /ws suffix — hooks already append /ws/<channel>
  const stripped = url.replace(/\/$/, "").replace(/\/ws$/, "");
  if (stripped !== url.replace(/\/$/, "") && process.env.NODE_ENV === "development") {
    console.warn(
      "[env] NEXT_PUBLIC_WS_BASE_URL contains /ws suffix which was automatically stripped. " +
      "Set the value to the bare origin (e.g. wss://your-api.up.railway.app) to avoid double /ws paths."
    );
  }
  return stripped;
}

/**
 * Validates env at boot (call from root layout or _app).
 * Non-throwing — only logs warnings.
 */
export function validateEnv(): void {
  if (typeof window === "undefined") return;

  const wsUrlRaw = process.env.NEXT_PUBLIC_WS_BASE_URL;
  const wsUrl = typeof wsUrlRaw === "string" ? wsUrlRaw.trim() : "";
  const isVercel =
    window.location.hostname.includes("vercel") ||
    window.location.hostname.includes(".app");

  if ((!wsUrl || wsUrl.trim() === "") && isVercel && process.env.NODE_ENV === "development") {
    console.warn(
      "[env] NEXT_PUBLIC_WS_BASE_URL is not configured. " +
      "Live data channels will not connect on Vercel. " +
      "Set NEXT_PUBLIC_WS_BASE_URL to your Railway backend wss:// URL."
    );
  }

  // Legacy env var guard
  if (process.env.NEXT_PUBLIC_WS_URL && process.env.NODE_ENV === "development") {
    console.warn(
      "[env] NEXT_PUBLIC_WS_URL is deprecated and has no effect. " +
      "Use NEXT_PUBLIC_WS_BASE_URL instead."
    );
  }

  const apiOverrideRaw = process.env.NEXT_PUBLIC_API_BASE_URL;
  const apiOverride = typeof apiOverrideRaw === "string" ? apiOverrideRaw.trim() : "";
  if (apiOverride && process.env.NODE_ENV === "development") {
    console.info("[env] REST override active: NEXT_PUBLIC_API_BASE_URL =", apiOverride);
  }
}

// Legacy export kept for existing imports — resolves identically to getApiBaseUrl().
const apiBaseConstRaw = process.env.NEXT_PUBLIC_API_BASE_URL;
export const API_BASE_URL = typeof apiBaseConstRaw === "string" ? apiBaseConstRaw.trim() : "";
