/**
 * @deprecated This file is NOT used by Next.js. The active config is next.config.js.
 * Kept for reference only. Key differences from next.config.js:
 *   - Uses API_BASE_URL instead of INTERNAL_API_URL
 *   - /auth/:path* → /auth/:path* (WRONG — backend expects /api/auth/:path*)
 *   - Missing standalone output toggle
 *   - hardcoded output: "standalone" (breaks Vercel)
 * DO NOT rename this to next.config.js without fixing the above.
 */
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
    // Resolve the backend API base URL for server-side proxy rewrites.
    // Check in order: API_BASE_URL (from Vercel env),
    // NEXT_PUBLIC_API_BASE_URL (if set at build time),
    // or localhost for local dev.
    const apiBase =
      process.env.API_BASE_URL ||
      process.env.NEXT_PUBLIC_API_BASE_URL ||
      "http://localhost:8000";
    console.log("[v0] next.config rewrites: apiBase =", apiBase);
    return [
      // /api/:path* — proxy REST API calls
      {
        source: "/api/:path*",
        destination: `${apiBase}/api/:path*`,
      },
      // /auth/* — auth endpoints
      {
        source: "/auth/:path*",
        destination: `${apiBase}/auth/:path*`,
      },
      // /preferences — preferences endpoints
      {
        source: "/preferences",
        destination: `${apiBase}/preferences`,
      },
      {
        source: "/preferences/:path*",
        destination: `${apiBase}/preferences/:path*`,
      },
      // /pipeline — pipeline endpoints
      {
        source: "/pipeline/:path*",
        destination: `${apiBase}/pipeline/:path*`,
      },
      // /ws/* — WebSocket proxy
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
