// Resolve the backend API base URL for server-side proxy rewrites.
// Prefer server-side INTERNAL_API_URL (not exposed to browser),
// then fall back to the public env var, then localhost for local dev.
// IMPORTANT: this must be the base origin (e.g. https://api.example.com)
// WITHOUT a /api suffix — the rewrite rules below already append /api/:path*.
const rawApiBase =
  process.env.INTERNAL_API_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://localhost:8000";

// Normalize: strip trailing slash and any accidental /api suffix to prevent
// double-prefix (/api/api/...) when combined with rewrite destinations.
const apiBase = rawApiBase.replace(/\/+$/, "").replace(/\/api$/, "");

// Warn at build time if apiBase is localhost in a production-ish environment.
// This means Next.js rewrites will proxy to nothing in production.
if (
  apiBase.includes("localhost") &&
  (process.env.NODE_ENV === "production" || process.env.VERCEL === "1")
) {
  console.warn(
    "\n⚠️  [next.config] WARNING: apiBase resolved to",
    apiBase,
    "\n   Set INTERNAL_API_URL env var to your Railway backend URL.",
    "\n   All API rewrites will fail in production without this!\n"
  );
}

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
      // /health — backend health check endpoint (does NOT have /api prefix)
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
