// Resolve the backend API base URL for server-side proxy rewrites.
// Prefer server-side INTERNAL_API_URL (not exposed to browser),
// then fall back to the public env var.
// IMPORTANT: this must be the base origin (e.g. https://api.example.com)
// WITHOUT a /api suffix — the rewrite rules below already append /api/:path*.
const isProd =
  process.env.NODE_ENV === "production" || process.env.VERCEL === "1";

// Read backend URL from all possible env var names across different platforms:
//   INTERNAL_API_URL          — Vercel (set manually in project vars)
//   NEXT_PUBLIC_API_BASE_URL  — Vercel (public, set manually in project vars)
//   API_BASE_URL              — Railway (set in railway service vars)
//   API_DOMAIN                — Railway (alternative domain var in railway)
const rawApiBase =
  process.env.INTERNAL_API_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  process.env.API_BASE_URL ||
  (process.env.API_DOMAIN
    ? `https://${process.env.API_DOMAIN}`
    : "") ||
  "";

// Warn loudly in production when env vars are missing.
// Previously this was a hard throw, but that blocks CI builds (e.g. GitHub Actions)
// that compile the app without a live backend URL. Downgraded to console.error so
// the build can complete; the rewrites will point to a non-functional placeholder.
if (isProd && !rawApiBase) {
  console.error(
    "[next.config] WARNING: Missing INTERNAL_API_URL or NEXT_PUBLIC_API_BASE_URL in production. " +
    "All API rewrites will route to a placeholder and will NOT work. " +
    "Set this in Vercel/Railway env vars before deploying."
  );
}

// Fallback — localhost for local dev, placeholder for production without env vars.
const resolvedBase = rawApiBase || "http://localhost:8000";

// Normalize: strip trailing slash and any accidental /api suffix to prevent
// double-prefix (/api/api/...) when combined with rewrite destinations.
const apiBase = resolvedBase.replace(/\/+$/, "").replace(/\/api$/, "");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Expose the resolved backend URL to the client bundle so NEXT_PUBLIC_
  // env var checks in DataStreamDiagnostic / runtimeHealth work correctly
  // even when the user only set API_BASE_URL on Railway.
  env: {
    NEXT_PUBLIC_API_BASE_URL: apiBase,
    NEXT_PUBLIC_WS_BASE_URL:
      process.env.NEXT_PUBLIC_WS_BASE_URL ||
      apiBase.replace(/^https:\/\//, "wss://").replace(/^http:\/\//, "ws://"),
  },
  // standalone is required for Docker/Railway (self-hosted) but must NOT be
  // used on Vercel — it breaks route-group resolution. Set the env var in
  // Dockerfile / railway.toml only.
  ...(process.env.NEXT_OUTPUT_STANDALONE === "true" && { output: "standalone" }),
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          {
            key: "Content-Security-Policy",
            value: [
              "default-src 'self'",
              "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
              "font-src https://fonts.gstatic.com",
              "connect-src 'self' wss://*.railway.app https://*.railway.app",
              "img-src 'self' data:",
              "script-src 'self' 'unsafe-eval' 'unsafe-inline'",
            ].join("; "),
          },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
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
        destination: `${apiBase}/api/v1/preferences`,
      },
      {
        source: "/preferences/:path*",
        destination: `${apiBase}/api/v1/preferences/:path*`,
      },
      // /pipeline — pipelineDagService calls /pipeline/dag
      {
        source: "/pipeline/:path*",
        destination: `${apiBase}/api/v1/pipeline/:path*`,
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
