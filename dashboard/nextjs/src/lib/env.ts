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
 *   NEXT_PUBLIC_WS_BASE_URL    required  bare wss:// ORIGIN for Railway — NO path suffix!
 *                                        e.g. wss://wolf15-api.up.railway.app  (NOT .../ws/live)
 *
 * REMOVED (do NOT use):
 *   NEXT_PUBLIC_WS_URL         was in wsService.ts (deleted) — never set this
 *   NEXT_PUBLIC_API_URL        legacy alias — use NEXT_PUBLIC_API_BASE_URL
 */

// ── Typed configuration error ─────────────────────────────────

/**
 * Thrown at startup when a required environment variable is missing or invalid
 * on a production/deployed environment.
 */
export class ConfigError extends Error {
  readonly code: string;
  readonly missingVars: string[];

  constructor(message: string, code: string, missingVars: string[] = []) {
    super(message);
    this.name = "ConfigError";
    this.code = code;
    this.missingVars = missingVars;
  }
}

// ── Environment status ────────────────────────────────────────

export interface EnvStatus {
  /** True when all required env vars are present and valid. */
  isValid: boolean;
  /** Human-readable error messages for each missing/invalid var. */
  errors: string[];
  /** Resolved WebSocket base URL (empty when misconfigured). */
  wsUrl: string;
  /** Resolved REST API base URL. */
  apiUrl: string;
}

/**
 * Returns the deployment status of all required env vars.
 * Safe to call in React render — never throws.
 *
 * NOTE: checks the env var directly (not the derived URL) so that the
 * local-dev localhost fallback in getWsBaseUrl() does not hide a
 * misconfigured deployment from the UI banner.
 */
export function getEnvStatus(): EnvStatus {
  const wsEnvVar = (process.env.NEXT_PUBLIC_WS_BASE_URL || "").trim();
  const wsUrl = getWsBaseUrl();
  const apiUrl = getApiBaseUrl();
  const errors: string[] = [];

  if (!wsEnvVar) {
    errors.push(
      "NEXT_PUBLIC_WS_BASE_URL is not set. All live data streams will be unavailable. " +
      "Set it to your Railway wss:// origin (e.g. wss://your-api.up.railway.app)."
    );
  }

  return { isValid: errors.length === 0, errors, wsUrl, apiUrl };
}

// ── Helper: detect deployed (non-local) host ──────────────────

function _isDeployedHost(): boolean {
  if (typeof window === "undefined") return false;
  const host = window.location.hostname;
  return (
    host.includes("vercel") ||
    host.includes(".app") ||
    host.includes(".railway") ||
    (!host.includes("localhost") && !host.includes("127.0.0.1") && host !== "")
  );
}

/**
 * Returns the REST API base URL.
 *
 * Default: empty string (relative) — Next.js rewrite /api/* handles proxying.
 * Override with NEXT_PUBLIC_API_BASE_URL for direct backend calls (dev/debug).
 */
export function getApiBaseUrl(): string {
  // Literal identifiers only — Next.js inlines NEXT_PUBLIC_* at build time.
  // DO NOT assign to intermediate variables.
  return (process.env.NEXT_PUBLIC_API_BASE_URL || process.env.NEXT_PUBLIC_API_URL || "")
    .trim()
    .replace(/\/$/, "");
}

/**
 * Returns the WebSocket base URL.
 *
 * On Vercel/deployed: NEXT_PUBLIC_WS_BASE_URL MUST be set to the Railway wss:// URL.
 * Vercel serverless functions cannot handle WebSocket upgrades — /ws/* rewrites
 * in next.config.js are for local-dev only (via Next.js dev server proxy).
 *
 * Fallback (localhost only): derives ws:// or wss:// from window.location.host.
 * This ONLY works on localhost/127.0.0.1 in local dev.
 * On any deployed host, returns "" so callers hard-fail with onDegradation.
 */
export function getWsBaseUrl(): string {
  // Literal process.env.NEXT_PUBLIC_WS_BASE_URL — Next.js inlines at build time.
  // DO NOT assign to intermediate variable.
  if (!(process.env.NEXT_PUBLIC_WS_BASE_URL || "").trim()) {
    if (typeof window !== "undefined") {
      const host = window.location.hostname;
      const isLocalDev = host === "localhost" || host === "127.0.0.1" || host === "";
      if (isLocalDev) {
        // Local dev only: derive from window.location for Next.js dev-server WS proxy.
        const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
        return `${proto}//${window.location.host}`;
      }
      // On deployed hosts, return "" so callers (realtimeClient) hard-fail.
      return "";
    }
    return ""; // SSR fallback — not used for real connections
  }
  // Normalise: strip ALL path components using URL parsing — hooks already append /ws/<channel>.
  // Common misconfiguration: setting /ws/live (or /ws) causes double-prefix,
  // e.g. wss://host/ws/live/ws/live.  Return only the origin (protocol + host + port).
  const rawWsUrl = (process.env.NEXT_PUBLIC_WS_BASE_URL ?? "").trim();
  try {
    const parsed = new URL(rawWsUrl);
    const origin = `${parsed.protocol}//${parsed.host}`;
    if (parsed.pathname && parsed.pathname !== "/") {
      // Warn in all environments — this misconfiguration breaks WS in production.
      console.warn(
        `[env] NEXT_PUBLIC_WS_BASE_URL had unexpected path '${parsed.pathname}' which was stripped. ` +
        "Set the value to the bare origin only (e.g. wss://your-api.up.railway.app)."
      );
    }
    return origin;
  } catch {
    // URL parsing failed — log the issue and return a minimally cleaned value.
    console.warn(
      `[env] NEXT_PUBLIC_WS_BASE_URL='${rawWsUrl}' could not be parsed as a URL. ` +
      "Ensure it is a valid wss:// or ws:// origin (e.g. wss://your-api.up.railway.app)."
    );
    return rawWsUrl.replace(/\/$/, "");
  }
}

/**
 * Validates env at boot and throws ConfigError if required vars are missing
 * on a deployed (non-localhost) environment.
 *
 * Call from root layout or _app. In development, only logs warnings.
 *
 * @throws {ConfigError} When NEXT_PUBLIC_WS_BASE_URL is missing on a deployed host.
 */
export function validateEnv(): void {
  if (typeof window === "undefined") return;

  const isDeployed = _isDeployedHost();
  const missingVars: string[] = [];

  // Inline literal reads — Next.js inlines NEXT_PUBLIC_* at build time.
  const wsUrl = (process.env.NEXT_PUBLIC_WS_BASE_URL || "").trim();
  const apiUrl = (process.env.NEXT_PUBLIC_API_BASE_URL || "").trim();

  if (!wsUrl) {
    missingVars.push("NEXT_PUBLIC_WS_BASE_URL");
    const msg =
      "[env] CRITICAL: NEXT_PUBLIC_WS_BASE_URL is NOT SET. " +
      "All live data streams will fail. " +
      "Set it to: NEXT_PUBLIC_WS_BASE_URL=wss://your-api.up.railway.app (bare origin, NO /ws suffix).";
    if (isDeployed) {
      console.error(msg);
    } else {
      console.warn(msg);
    }
  }

  // INTERNAL_API_URL is server-side only — not available in browser.
  // Use NEXT_PUBLIC_API_BASE_URL as the proxy indicator on client side.
  if (!apiUrl && isDeployed) {
    missingVars.push("NEXT_PUBLIC_API_BASE_URL");
    console.error(
      "[env] CRITICAL: NEXT_PUBLIC_API_BASE_URL is NOT SET. " +
      "API calls will fall back to relative paths which may fail if the proxy is not configured. " +
      "Set it to: NEXT_PUBLIC_API_BASE_URL=https://your-api.up.railway.app (NO /api suffix)."
    );
  }

  // Legacy env var guard
  if (process.env.NEXT_PUBLIC_WS_URL) {
    console.warn(
      "[env] NEXT_PUBLIC_WS_URL is deprecated and has no effect. " +
      "Use NEXT_PUBLIC_WS_BASE_URL instead."
    );
  }

  if (apiUrl && process.env.NODE_ENV === "development") {
    console.info("[env] REST override active: NEXT_PUBLIC_API_BASE_URL =", apiUrl);
  }

  // Throw on deployed envs to give the UI a chance to show a hard error banner.
  if (isDeployed && !wsUrl) {
    throw new ConfigError(
      "Required environment variable NEXT_PUBLIC_WS_BASE_URL is not configured. " +
      "All live WebSocket streams will be unavailable. " +
      "Go to your deployment settings and add NEXT_PUBLIC_WS_BASE_URL=wss://your-api.up.railway.app",
      "ENV_WS_URL_MISSING",
      missingVars,
    );
  }
}

// Legacy export kept for existing imports — resolves identically to getApiBaseUrl().
export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || process.env.NEXT_PUBLIC_API_URL || "").trim().replace(/\/$/, "");
