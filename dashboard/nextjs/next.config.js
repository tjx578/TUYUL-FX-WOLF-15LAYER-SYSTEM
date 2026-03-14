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
    return [
      // /api/* — covers most service calls (e.g. /api/v1/trades, /api/v1/accounts)
      {
        source: "/api/:path*",
        destination: `${apiBase}/api/:path*`,
      },
      // /auth/* — used by sessionService (/auth/refresh) and login (/auth/session)
      {
        source: "/auth/:path*",
        destination: `${apiBase}/auth/:path*`,
      },
      // /preferences/* — used by preferencesService
      {
        source: "/preferences/:path*",
        destination: `${apiBase}/preferences/:path*`,
      },
      // /preferences (exact, no trailing segment)
      {
        source: "/preferences",
        destination: `${apiBase}/preferences`,
      },
      // /pipeline/* — used by pipelineDagService (/pipeline/dag)
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
