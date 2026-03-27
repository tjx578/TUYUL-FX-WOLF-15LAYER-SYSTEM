#!/usr/bin/env node

/**
 * validate-deploy-env.mjs
 * ────────────────────────
 * Pre-deploy check for required environment variables.
 *
 * Run before `next build` in CI/CD or Vercel build command to catch
 * misconfiguration early instead of silently deploying a broken dashboard.
 *
 * Usage:
 *   node scripts/validate-deploy-env.mjs          # exits 1 on missing vars
 *   node scripts/validate-deploy-env.mjs --warn   # prints warnings only (exit 0)
 *
 * Required env vars:
 *   NEXT_PUBLIC_WS_BASE_URL    — wss:// origin for WebSocket (Railway backend)
 *
 * Recommended env vars:
 *   NEXT_PUBLIC_API_BASE_URL   — REST API base (falls back to rewrite if unset)
 *   INTERNAL_API_URL           — Server-side proxy target (for /api/proxy runtime)
 */

const WARN_ONLY = process.argv.includes("--warn");

const errors = [];
const warnings = [];

// ── NEXT_PUBLIC_WS_BASE_URL (required) ────────────────────────

const wsUrl = (process.env.NEXT_PUBLIC_WS_BASE_URL || "").trim();

if (!wsUrl) {
  errors.push(
    "NEXT_PUBLIC_WS_BASE_URL is not set. WebSocket connections will fail.\n" +
    "  Set it to the Railway backend origin, e.g. wss://wolf15-api.up.railway.app"
  );
} else {
  if (!wsUrl.startsWith("wss://") && !wsUrl.startsWith("ws://")) {
    errors.push(
      `NEXT_PUBLIC_WS_BASE_URL must start with wss:// or ws://, got: "${wsUrl}"`
    );
  }
  if (wsUrl.includes("/ws/") || wsUrl.endsWith("/ws")) {
    errors.push(
      `NEXT_PUBLIC_WS_BASE_URL must be a bare origin (no path). Got: "${wsUrl}"\n` +
      "  Remove the path suffix. The multiplexer appends /ws/live automatically."
    );
  }
  if (wsUrl.includes(".vercel.app")) {
    errors.push(
      "NEXT_PUBLIC_WS_BASE_URL points to a Vercel domain. Vercel cannot upgrade WebSocket.\n" +
      "  Use the Railway backend origin instead."
    );
  }
}

// ── NEXT_PUBLIC_API_BASE_URL (recommended) ────────────────────

const apiUrl = (process.env.NEXT_PUBLIC_API_BASE_URL || "").trim();

if (!apiUrl) {
  warnings.push(
    "NEXT_PUBLIC_API_BASE_URL is not set. Build-time rewrites will point to localhost.\n" +
    "  The runtime proxy (/api/proxy) will handle REST calls, but adds latency.\n" +
    "  Set it to the Railway API origin, e.g. https://wolf15-api.up.railway.app"
  );
} else if (apiUrl.includes("localhost") || apiUrl.includes("127.0.0.1")) {
  warnings.push(
    `NEXT_PUBLIC_API_BASE_URL points to localhost ("${apiUrl}").\n` +
    "  This is fine for local dev but will break in production."
  );
}

// ── INTERNAL_API_URL (recommended for server-side proxy) ──────

const internalUrl = (process.env.INTERNAL_API_URL || "").trim();
if (!internalUrl && !apiUrl) {
  warnings.push(
    "Neither INTERNAL_API_URL nor NEXT_PUBLIC_API_BASE_URL is set.\n" +
    "  The runtime proxy (/api/proxy) needs at least one to reach the backend."
  );
}

// ── Output ────────────────────────────────────────────────────

if (warnings.length > 0) {
  console.warn("\n⚠  Deploy env warnings:\n");
  warnings.forEach((w, i) => console.warn(`  ${i + 1}. ${w}\n`));
}

if (errors.length > 0) {
  console.error("\n✗  Deploy env errors:\n");
  errors.forEach((e, i) => console.error(`  ${i + 1}. ${e}\n`));

  if (WARN_ONLY) {
    console.warn("  (--warn mode: continuing despite errors)\n");
  } else {
    console.error("  Set the missing env vars and retry, or use --warn to skip.\n");
    process.exit(1);
  }
} else if (warnings.length === 0) {
  console.log("✓  All deploy env vars look good.\n");
}
