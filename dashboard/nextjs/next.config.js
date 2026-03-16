// Resolve the backend API base URL for server-side proxy rewrites.
// Prefer server-side INTERNAL_API_URL (not exposed to browser),
// then fall back to the public env var.
// IMPORTANT: this must be the base origin (e.g. https://api.example.com)
// WITHOUT a /api suffix — the rewrite rules below already append /api/:path*.
const isProd =
  process.env.NODE_ENV === "production" || process.env.VERCEL === "1";

const rawApiBase =
  process.env.INTERNAL_API_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "";

// Hard fail in production — no silent localhost fallback.
if (isProd && !rawApiBase) {
  throw new Error(
    "[next.config] FATAL: Missing INTERNAL_API_URL or NEXT_PUBLIC_API_BASE_URL in production. " +
    "All API rewrites will route to nowhere. Set this in Vercel/Railway env vars."
  );
}

// Local dev fallback — only when env vars are absent AND not production.
const resolvedBase = rawApiBase || "http://localhost:8000";

// Normalize: strip trailing slash and any accidental /api suffix to prevent
// double-prefix (/api/api/...) when combined with rewrite destinations.
const apiBase = resolvedBase.replace(/\/+$/, "").replace(/\/api$/, "");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // standalone is required for Docker/Railway (self-hosted) but must NOT be
  // used on Vercel — it breaks route-group resolution. Set the env var in
  // Dockerfile / railway.toml only.
  ...(process.env.NEXT_OUTPUT_STANDALONE === "true" && { output: "standalone" }),
  async redirects() {
    return [
      {
        source: "/calendar",
        destination: "/news",
        permanent: false,
      },
    ];
  },
  async rewrites() {
    console.log("[next.config] rewrites apiBase =", apiBase);
    return [
      // /health — health checks called directly by frontend diagnostics/hooks
      {
        source: "/health",
        destination: `${apiBase}/health`,
      },
      {
        source: "/api/:path*",
        destination: `${apiBase}/api/:path*`,
      },
      // /auth/* — sessionService calls /auth/refresh; backend prefix is /api/auth
      {
        source: "/auth/:path*",
        destination: `${apiBase}/api/auth/:path*`,
      },
      // /preferences — preferencesService calls /preferences and /preferences/:id
      {
        source: "/preferences",
        destination: `${apiBase}/preferences`,
      },
      {
        source: "/preferences/:path*",
        destination: `${apiBase}/preferences/:path*`,
      },
      // /pipeline — pipelineDagService calls /pipeline/dag
      {
        source: "/pipeline/:path*",
        destination: `${apiBase}/pipeline/:path*`,
      },
      // NOTE: /ws/* WebSocket rewrite is intentionally removed.
      // Vercel serverless cannot upgrade WebSocket connections — the rewrite
      // appeared to work but silently failed in production.
      // WS connections MUST be direct: set NEXT_PUBLIC_WS_BASE_URL to the
      // Railway wss:// origin. Local dev still works via Next.js dev-server
      // proxy when NEXT_PUBLIC_WS_BASE_URL is unset (falls back to origin).
    ];
  },
  eslint: {
    // Allow builds to complete even if there are ESLint warnings/errors
    ignoreDuringBuilds: true,
  },
  typescript: {
    // Allow builds to complete even if there are TypeScript errors
    ignoreBuildErrors: false,
  },
};

module.exports = nextConfig;
