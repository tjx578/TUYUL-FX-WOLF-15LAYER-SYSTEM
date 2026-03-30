/**
 * TUYUL FX Wolf-15 — Environment Resolution
 *
 * Single source of truth for all env-derived config.
 *
 * Deployment rules:
 *   REST  → always through /api/proxy/[...path] runtime proxy.
 *          No build-time rewrites — the proxy reads INTERNAL_API_URL at
 *          request time, so stale-env bugs are impossible.
 *   WS    → MUST be direct  → Vercel cannot upgrade WebSocket connections.
 *          Set NEXT_PUBLIC_WS_BASE_URL to the Railway/backend wss:// origin.
 *
 * Env vars in use (exactly these two, nothing else):
 *   NEXT_PUBLIC_API_BASE_URL   optional  override REST base (default: relative via proxy)
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
  } else {
    // Check for path component — causes double-path connections at runtime.
    try {
      const parsed = new URL(wsEnvVar);
      if (parsed.pathname && parsed.pathname !== "/") {
        errors.push(
          `NEXT_PUBLIC_WS_BASE_URL contains a path ('${parsed.pathname}'). ` +
          "It must be a bare origin (protocol+host only, e.g. wss://your-api.up.railway.app). " +
          "Including a path causes double-path WebSocket connections (e.g. /ws/live/ws/live). " +
          "The path was automatically stripped but you should fix the env var."
        );
      }
    } catch {
      errors.push(
        `NEXT_PUBLIC_WS_BASE_URL='${wsEnvVar}' is not a valid URL. ` +
        "Use a full wss:// or ws:// origin (e.g. wss://your-api.up.railway.app)."
      );
    }
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
 * Default: empty string (relative) — all REST goes through /api/proxy.
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
 * Returns the WebSocket base URL as a bare origin (protocol + host, NO path).
 *
 * On Vercel/deployed: NEXT_PUBLIC_WS_BASE_URL MUST be set to the Railway wss:// URL.
 * Vercel serverless functions cannot handle WebSocket upgrades — /ws/* rewrites
 * in next.config.js are for local-dev only (via Next.js dev server proxy).
 *
 * Fallback (localhost only): derives ws:// or wss:// from window.location.host.
 * This ONLY works on localhost/127.0.0.1 in local dev.
 * On any deployed host, returns "" so callers hard-fail with onDegradation.
 *
 * IMPORTANT: Always returns the bare origin only (protocol+host). Any path in the env
 * var (e.g. /ws/live) is auto-stripped with a warning — hooks append /ws/<channel>
 * themselves, so including a path causes double-path connections (wss://host/ws/live/ws/live).
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
  // Use URL parsing to extract bare origin — strips ALL path components.
  // This prevents double-path bugs when the env var includes /ws, /ws/live, or
  // any other path that hooks already append (e.g. wss://host/ws/live/ws/live).
  const raw = (process.env.NEXT_PUBLIC_WS_BASE_URL ?? "").trim();
  try {
    const parsed = new URL(raw);
    const hasPath = parsed.pathname && parsed.pathname !== "/";
    if (hasPath) {
      console.warn(
        `[env] NEXT_PUBLIC_WS_BASE_URL contains path '${parsed.pathname}' which was automatically stripped. ` +
        "Set the value to the bare origin only (e.g. wss://your-api.up.railway.app). " +
        "Including a path causes double-path WebSocket connections (e.g. /ws/live/ws/live)."
      );
    }
    return `${parsed.protocol}//${parsed.host}`;
  } catch {
    // Fallback for malformed URLs: strip everything after the host portion.
    // Only attempt stripping if the raw value starts with a ws:// or wss:// scheme;
    // otherwise return empty string to let callers hard-fail safely.
    const schemeEnd = raw.startsWith("wss://") ? 6 : raw.startsWith("ws://") ? 5 : -1;
    if (schemeEnd < 0) return "";
    const pathStart = raw.indexOf("/", schemeEnd);
    return pathStart > 0 ? raw.slice(0, pathStart) : raw;
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
      "Set it to: NEXT_PUBLIC_WS_BASE_URL=wss://your-api.up.railway.app (bare origin, NO path like /ws/live).";
    if (isDeployed) {
      console.error(msg);
    } else {
      console.warn(msg);
    }
  } else {
    // Validate that the URL is a bare origin (no path component).
    // A path causes double-path connections: wss://host/ws/live/ws/live.
    try {
      const parsed = new URL(wsUrl);
      if (parsed.pathname && parsed.pathname !== "/") {
        const msg =
          `[env] INVALID: NEXT_PUBLIC_WS_BASE_URL='${wsUrl}' contains path '${parsed.pathname}'. ` +
          "It must be a bare origin — protocol+host only (e.g. wss://your-api.up.railway.app). " +
          "Including a path causes double-path WebSocket connections (e.g. /ws/live/ws/live). " +
          "Fix the env var: remove everything after the hostname.";
        console.error(msg);
        missingVars.push("NEXT_PUBLIC_WS_BASE_URL");
        throw new ConfigError(
          `NEXT_PUBLIC_WS_BASE_URL must be a bare origin (protocol+host only), ` +
          `but got '${wsUrl}' which contains path '${parsed.pathname}'. ` +
          "Remove the path — hooks append /ws/<channel> automatically. " +
          "Correct value: wss://your-api.up.railway.app",
          "ENV_WS_URL_HAS_PATH",
          missingVars,
        );
      }
    } catch (err) {
      if (err instanceof ConfigError) throw err;
      // URL parse failure
      const msg =
        `[env] INVALID: NEXT_PUBLIC_WS_BASE_URL='${wsUrl}' is not a valid URL. ` +
        "Use a full wss:// or ws:// origin (e.g. wss://your-api.up.railway.app).";
      console.error(msg);
      missingVars.push("NEXT_PUBLIC_WS_BASE_URL");
      throw new ConfigError(msg, "ENV_WS_URL_INVALID", missingVars);
    }
  }

  // INTERNAL_API_URL is server-side only — not available in browser.
  // Use NEXT_PUBLIC_API_BASE_URL as the proxy indicator on client side.
  if (!apiUrl && isDeployed) {
    missingVars.push("NEXT_PUBLIC_API_BASE_URL");
    console.error(
      "[env] CRITICAL: NEXT_PUBLIC_API_BASE_URL is NOT SET. " +
      "The runtime proxy reads INTERNAL_API_URL server-side, but this client-side var " +
      "is needed for diagnostics and SSE. " +
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

// ── Runtime proxy — single canonical path ──────────────────────────────
//
// P4 consolidation: all REST calls go through /api/proxy/[...path].
// Build-time rewrites have been removed. The runtime proxy reads
// INTERNAL_API_URL at request time, eliminating stale-env bugs.

/**
 * Returns the URL prefix that client-side fetch calls should prepend.
 *
 * Always returns "/api/proxy" on client (browser).
 * Returns "" on server (SSR/RSC) — server code should use INTERNAL_API_URL directly.
 *
 * Callers use it like:  fetch(`${getRestPrefix()}/api/v1/trades/active`)
 * The resulting URL /api/proxy/api/v1/trades/active is handled by the
 * catch-all route handler which forwards to the backend.
 */
export function getRestPrefix(): string {
  // Server-side rendering — return empty; server code should use backend URL directly.
  if (typeof window === "undefined") return "";
  return "/api/proxy";
}

// Legacy export kept for existing imports — resolves identically to getApiBaseUrl().
export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || process.env.NEXT_PUBLIC_API_URL || "").trim().replace(/\/$/, "");
