/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  
  // API + WebSocket proxy to FastAPI backend
  async rewrites() {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    return [
      {
        source: '/api/:path*',
        destination: `${apiUrl}/api/:path*`,
      },
      // WebSocket proxy (Next.js dev server)
      {
        source: '/ws/:path*',
        destination: `${apiUrl}/ws/:path*`,
      },
    ];
  },
  
  // Headers for security
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          {
            key: 'X-Frame-Options',
            value: 'SAMEORIGIN',
          },
          {
            key: 'X-Content-Type-Options',
            value: 'nosniff',
          },
        ],
      },
    ];
  },
  
     // Optimize production build
     // swcMinify: true, // Deprecated in Next.js 14+
  
  // Output standalone for Docker/VPS
  output: 'standalone',
};

module.exports = nextConfig;
