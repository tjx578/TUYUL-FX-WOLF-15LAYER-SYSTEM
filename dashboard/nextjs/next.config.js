// Resolve the backend API base URL for server-side proxy rewrites.
// Prefer server-side INTERNAL_API_URL (not exposed to browser),
// then fall back to the public env var, then localhost for local dev.
const apiBase =
  process.env.INTERNAL_API_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://localhost:8000";

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
