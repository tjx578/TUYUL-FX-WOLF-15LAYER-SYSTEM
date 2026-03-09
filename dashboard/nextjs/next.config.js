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
