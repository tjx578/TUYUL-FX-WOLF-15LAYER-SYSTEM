/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  
  // API + WebSocket proxy to FastAPI backend (Railway)
  // NOTE: In production on Vercel, the edge-level rewrites in vercel.json
  // take priority (faster). These app-level rewrites are the fallback and
  // are the primary mechanism during local `next dev`.
  async rewrites() {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    return [
      {
        source: '/api/:path*',
        destination: `${apiUrl}/api/:path*`,
      },
      // WebSocket proxy (Next.js dev server / fallback)
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
