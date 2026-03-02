/**
 * Centralized env access for NEXT_PUBLIC_ vars.
 * process.env.NEXT_PUBLIC_* is replaced at build time by Next.js.
 */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

/**
 * Validates required public environment variables at runtime.
 * Call once at app startup (e.g. in layout.tsx or root page).
 * Does NOT throw — logs warnings so the dashboard stays up.
 */

const REQUIRED_PUBLIC_VARS: string[] = [
  "NEXT_PUBLIC_API_URL",
];

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
 * Returns API base URL with a safe fallback for local dev.
 * Logs a warning if falling back so it is visible in browser console.
 */
export function getApiBaseUrl(): string {
  const url = process.env.NEXT_PUBLIC_API_URL;
  if (!url || url.trim() === "") {
    const fallback = "http://localhost:8000";
    console.warn(
      `[env] NEXT_PUBLIC_API_URL not set — falling back to ${fallback}`
    );
    return fallback;
  }
  return url.replace(/\/$/, ""); // strip trailing slash
}