/**
 * Centralized env access for NEXT_PUBLIC_ vars.
 * process.env.NEXT_PUBLIC_* is replaced at build time by Next.js.
 *
 * Required env vars:
 *   NEXT_PUBLIC_API_BASE_URL   — backend REST base  (e.g. https://api.domain.com)
 *   NEXT_PUBLIC_WS_BASE_URL    — backend WS base    (e.g. wss://api.domain.com/ws)
 */

// Legacy export kept for existing imports — reads from NEXT_PUBLIC_API_BASE_URL.
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

const REQUIRED_PUBLIC_VARS: string[] = [
  "NEXT_PUBLIC_API_BASE_URL",
  "NEXT_PUBLIC_WS_BASE_URL",
];

/**
 * Validates required public environment variables at runtime.
 * Call once at app startup (e.g. in layout.tsx or root page).
 * Does NOT throw — logs warnings so the dashboard stays up.
 */
export function validateEnv(): void {
  const missing: string[] = [];

  for (const key of REQUIRED_PUBLIC_VARS) {
    const val = process.env[key];
    if (!val || val.trim() === "") {
      missing.push(key);
    }
  }

  if (missing.length > 0) {
    console.warn(
      "[env] WARNING: Missing required env vars:",
      missing.join(", "),
      "— dashboard may show blank or stale data."
    );
  }
}

/**
 * Returns REST API base URL.
 * Canonical source: NEXT_PUBLIC_API_BASE_URL.
 * Falls back to NEXT_PUBLIC_API_URL for backward compatibility.
 */
export function getApiBaseUrl(): string {
  const url =
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    process.env.NEXT_PUBLIC_API_URL;
  if (!url || url.trim() === "") {
    const fallback = "http://localhost:8000";
    console.warn(`[env] NEXT_PUBLIC_API_BASE_URL not set — falling back to ${fallback}`);
    return fallback;
  }
  return url.replace(/\/$/, ""); // strip trailing slash
}

/**
 * Returns WebSocket base URL.
 * Canonical source: NEXT_PUBLIC_WS_BASE_URL.
 *
 * Why explicit? Deriving via replace(/^http/, "ws") produces ws:// on plain
 * HTTP origins and breaks on wss:// in production. Always set this explicitly.
 */
export function getWsBaseUrl(): string {
  const url = process.env.NEXT_PUBLIC_WS_BASE_URL;
  if (!url || url.trim() === "") {
    const fallback = "ws://localhost:8000/ws";
    console.warn(`[env] NEXT_PUBLIC_WS_BASE_URL not set — falling back to ${fallback}`);
    return fallback;
  }
  return url.replace(/\/$/, ""); // strip trailing slash
}