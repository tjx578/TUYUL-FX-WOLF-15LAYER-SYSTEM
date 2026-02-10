# TUYUL FX WOLF 15-LAYER SYSTEM - Next.js Dashboard

Professional trading system dashboard built with Next.js 14, TypeScript, and Tailwind CSS.

## Features

- 🐺 **L12 Verdict Display** - Real-time trading verdicts with wolf status
- 🚪 **9-Gate Constitutional Validation** - Visual gate status indicators
- ⚡ **Execution State Monitor** - Current order status tracking
- 🌍 **Dual Timezone Display** - Shows both UTC and GMT+8 (Asia/Singapore)
- 📊 **System Health Monitoring** - Latency and service status
- 🔄 **Auto-refresh** - SWR-powered data fetching with configurable intervals
- 🎨 **Dark Theme** - Professional wolf-themed UI
- 📱 **Responsive Design** - Works on desktop, tablet, and mobile

## Tech Stack

- **Framework**: Next.js 14 (App Router)
- **Language**: TypeScript
- **Styling**: Tailwind CSS
- **Data Fetching**: SWR
- **Icons**: Lucide React
- **Timezone**: date-fns-tz

## Quick Start

### Prerequisites

- Node.js 18+ and npm 9+
- FastAPI backend running on `http://localhost:8000`

### Installation

```bash
# Navigate to dashboard directory
cd dashboard/nextjs

# Install dependencies
npm install

# Copy environment file
cp .env.example .env

# Edit .env with your settings
nano .env
```

### Development

```bash
# Start development server
npm run dev

# Open browser
open http://localhost:3000
```

### Production Build

```bash
# Build for production
npm run build

# Start production server
npm start
```

## Environment Variables

Create `.env` file from `.env.example`:

```env
# API Backend URL
NEXT_PUBLIC_API_URL=http://localhost:8000

# Timezone for display
NEXT_PUBLIC_TIMEZONE=Asia/Singapore

# Refresh intervals (milliseconds)
NEXT_PUBLIC_VERDICT_REFRESH_MS=5000
NEXT_PUBLIC_CONTEXT_REFRESH_MS=10000
NEXT_PUBLIC_HEALTH_REFRESH_MS=30000

# Dashboard title
NEXT_PUBLIC_APP_NAME="TUYUL FX WOLF 15-LAYER"
```

## Project Structure

```
dashboard/nextjs/
├── src/
│   ├── app/              # Next.js App Router
│   │   ├── layout.tsx    # Root layout
│   │   ├── page.tsx      # Home page
│   │   └── globals.css   # Global styles
│   ├── components/       # React components
│   │   ├── VerdictCard.tsx       # L12 verdict display
│   │   ├── GateStatus.tsx        # 9-gate status
│   │   ├── PairSelector.tsx      # Currency pair selector
│   │   ├── ExecutionPanel.tsx    # Execution state
│   │   ├── TimezoneDisplay.tsx   # UTC/GMT+8 clock
│   │   └── SystemHealth.tsx      # System health monitor
│   ├── lib/              # Utilities
│   │   ├── api.ts        # API client with SWR hooks
│   │   └── timezone.ts   # Timezone utilities
│   └── types/            # TypeScript types
│       └── index.ts      # Type definitions
├── public/               # Static assets
├── next.config.js        # Next.js configuration
├── tailwind.config.js    # Tailwind CSS configuration
├── tsconfig.json         # TypeScript configuration
├── package.json          # Dependencies
└── README.md             # This file
```

## API Endpoints Required

The dashboard expects these FastAPI endpoints:

### Core Endpoints

- `GET /api/v1/l12/{pair}` - Get L12 verdict for a pair
- `GET /api/v1/verdict/all` - Get all verdicts
- `GET /api/v1/context` - Get live context snapshot
- `GET /api/v1/execution` - Get execution state
- `GET /api/v1/pairs` - Get available currency pairs
- `GET /health` - System health check

### Response Formats

See `src/types/index.ts` for TypeScript type definitions matching expected API responses.

## Development

### Adding New Components

1. Create component in `src/components/`
2. Use SWR hooks from `src/lib/api.ts` for data fetching
3. Import and use in `src/app/page.tsx`

### Adding New API Endpoints

1. Add hook in `src/lib/api.ts`
2. Define types in `src/types/index.ts`
3. Use hook in components

### Styling

- Uses Tailwind CSS with custom wolf theme colors
- Theme colors defined in `tailwind.config.js`
- Global styles in `src/app/globals.css`

## Production Deployment

### Docker

```bash
# Build Docker image
docker build -t tuyulfx-dashboard .

# Run container
docker run -p 3000:3000 \
  -e NEXT_PUBLIC_API_URL=http://api:8000 \
  tuyulfx-dashboard
```

### Systemd Service

See `deploy/hostinger/tuyulfx-dashboard.service` for systemd configuration.

### Nginx Reverse Proxy

See `deploy/hostinger/nginx.conf` for Nginx configuration.

## Troubleshooting

### API Connection Issues

```bash
# Check API is running
curl http://localhost:8000/health

# Check environment variables
cat .env

# Check browser console for errors
```

### Build Errors

```bash
# Clear Next.js cache
rm -rf .next

# Reinstall dependencies
rm -rf node_modules package-lock.json
npm install

# Rebuild
npm run build
```

### Styling Issues

```bash
# Rebuild Tailwind CSS
npm run dev
```

## Performance

- Uses SWR for efficient data fetching and caching
- Implements stale-while-revalidate strategy
- Optimizes with Next.js image optimization
- Standalone output for minimal Docker images

## Security

- No write operations (read-only dashboard)
- CORS configured for API access
- Security headers in Next.js config
- No sensitive data in client-side code

## Contributing

1. Follow TypeScript best practices
2. Use Tailwind CSS for styling
3. Test on multiple screen sizes
4. Ensure timezone display is accurate
5. Update types when API changes

## License

Part of TUYUL FX WOLF 15-LAYER SYSTEM

---

**Happy Trading! 🐺**
