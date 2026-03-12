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
    const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${apiBase}/api/:path*`,
      },
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
