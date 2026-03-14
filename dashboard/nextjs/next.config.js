/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
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
    // Prefer server-side INTERNAL_API_URL (not exposed to browser),
    // then fall back to the public env var, then localhost for local dev.
    const apiBase =
      process.env.INTERNAL_API_URL ||
      process.env.NEXT_PUBLIC_API_BASE_URL ||
      "http://localhost:8000";
    console.log("[next.config] rewrites apiBase =", apiBase);
    return [
      // /api/:path* — strip the leading /api prefix and forward to the backend.
      // The backend already includes /api in its own router prefixes, so
      // /api/v1/trades  → ${apiBase}/v1/trades  ✓
      // /api/auth/session → ${apiBase}/auth/session ✓  (backend prefix is /api/auth)
      // Wait — backend router prefix is /api/auth, so destination must keep /api.
      // Solution: keep /api in destination so /api/auth/session → ${apiBase}/api/auth/session.
      // But /api/v1/trades → ${apiBase}/api/v1/trades also needs /api retained.
      // Therefore: rewrite /api/:path* → ${apiBase}/api/:path* is correct AS LONG AS
      // no service prefixes its call path with /api AGAIN.  Services already use full
      // paths like /api/v1/trades (no double-prefix), so this is fine.
      {
        source: "/api/:path*",
        destination: `${apiBase}/api/:path*`,
      },
      // /auth/* — sessionService calls /auth/refresh (no /api prefix)
      {
        source: "/auth/:path*",
        destination: `${apiBase}/auth/:path*`,
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
      // /ws/* — WebSocket upgrade proxy
      {
        source: "/ws/:path*",
        destination: `${apiBase}/ws/:path*`,
      },
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
