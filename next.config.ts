import type { NextConfig } from "next";

// ---------------------------------------------------------------------------
// Backend API base URL resolution (server-side, never exposed to the browser).
//
// Resolution order:
//   1. INTERNAL_API_URL  — Railway private-network URL (preferred in production)
//   2. NEXT_PUBLIC_API_BASE_URL — explicit public override (also used by client)
//   3. API_BASE_URL       — legacy alias
//   4. API_DOMAIN         — construct https:// URL from domain-only var
//   5. http://localhost:8000 — local dev fallback
//
// The resolved URL is used for server-side Next.js rewrites only.
// The `env` block below additionally bakes NEXT_PUBLIC_API_BASE_URL into the
// client bundle so client components can reference
// `process.env.NEXT_PUBLIC_API_BASE_URL` without a separate Vercel variable.
// ---------------------------------------------------------------------------
function _firstNonEmpty(...values: (string | undefined)[]): string {
  for (const v of values) {
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return "";
}

const rawApiBase = _firstNonEmpty(
  process.env.INTERNAL_API_URL,
  process.env.NEXT_PUBLIC_API_BASE_URL,
  process.env.API_BASE_URL,
  process.env.API_DOMAIN ? `https://${process.env.API_DOMAIN}` : undefined,
);

// Strip trailing slash and accidental /api suffix to avoid double-prefix.
const apiBase = (rawApiBase || "http://localhost:8000")
  .replace(/\/+$/, "")
  .replace(/\/api$/, "");

// WebSocket base — derive from apiBase when not explicitly set.
const wsBase = _firstNonEmpty(
  process.env.NEXT_PUBLIC_WS_BASE_URL,
  apiBase.replace(/^https:\/\//, "wss://").replace(/^http:\/\//, "ws://"),
);

const nextConfig: NextConfig = {
  reactStrictMode: true,
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: false,
  },
  // Bake resolved URLs into the client bundle.
  // This ensures NEXT_PUBLIC_API_BASE_URL is always available in the browser
  // even when the operator only set INTERNAL_API_URL or API_DOMAIN on Railway.
  env: {
    NEXT_PUBLIC_API_BASE_URL: apiBase,
    NEXT_PUBLIC_WS_BASE_URL: wsBase,
  },
  async rewrites() {
    // Proxy /api/* and /health to the Railway API backend so client components
    // can use relative paths (e.g. fetch("/api/v1/health")) without CORS issues.
    return [
      {
        source: "/health",
        destination: `${apiBase}/health`,
      },
      {
        source: "/api/:path*",
        destination: `${apiBase}/api/:path*`,
      },
      {
        source: "/auth/:path*",
        destination: `${apiBase}/api/auth/:path*`,
      },
    ];
  },
};

export default nextConfig;
