// Resolve the backend API base URL for server-side proxy rewrites.
// Prefer server-side INTERNAL_API_URL (not exposed to browser),
// then fall back to the public env var.
// IMPORTANT: this must be the base origin (e.g. https://api.example.com)
// WITHOUT a /api suffix — the rewrite rules below already append /api/:path*.
const isProd =
  process.env.NODE_ENV === "production" || process.env.VERCEL === "1";

function _firstNonEmpty(...values) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return "";
}

function _isProtectedDeployment() {
  const explicitFailFast = _firstNonEmpty(
    process.env.NEXT_CONFIG_FAIL_FAST,
    process.env.NEXT_CONFIG_PROTECTED_ENV,
  );
  if (["1", "true", "yes"].includes(explicitFailFast.toLowerCase())) {
    return true;
  }

  const vercelEnv = _firstNonEmpty(process.env.VERCEL_ENV).toLowerCase();
  if (vercelEnv === "production") {
    return true;
  }

  const railwayEnv = _firstNonEmpty(process.env.RAILWAY_ENVIRONMENT).toLowerCase();
  if (railwayEnv === "production") {
    return true;
  }

  const branch = _firstNonEmpty(
    process.env.VERCEL_GIT_COMMIT_REF,
    process.env.RAILWAY_GIT_BRANCH,
    process.env.GITHUB_REF_NAME,
    process.env.CI_BRANCH,
  ).toLowerCase();
  return branch === "main" || branch === "master";
}

function _normalizeWsBase(value) {
  const raw = (value || "").trim();
  if (!raw) return "";

  // Aggressively strip any path component — we only want the origin.
  // Common mistakes: trailing slash, /ws, /ws/, /api/ws, etc.
  try {
    const url = new URL(raw);
    // Rebuild as bare origin (protocol + host + port only)
    return `${url.protocol}//${url.host}`;
  } catch {
    // If URL parsing fails, fallback to regex stripping
    return raw.replace(/\/+$/, "").replace(/\/ws.*$/, "").replace(/\/api.*$/, "");
  }
}

function _validateWsBase(wsBase, { protectedDeploy, explicitlyConfigured }) {
  if (protectedDeploy && !explicitlyConfigured) {
    throw new Error(
      "[next.config] Missing NEXT_PUBLIC_WS_BASE_URL for protected deployment. " +
      "Set it to your Railway websocket origin (e.g. wss://<service>.up.railway.app)."
    );
  }

  if (!wsBase) {
    return;
  }

  let parsed;
  try {
    parsed = new URL(wsBase);
  } catch {
    throw new Error(
      `[next.config] Invalid NEXT_PUBLIC_WS_BASE_URL='${wsBase}'. Use a full ws:// or wss:// origin.`
    );
  }

  if (parsed.protocol !== "ws:" && parsed.protocol !== "wss:") {
    throw new Error(
      `[next.config] NEXT_PUBLIC_WS_BASE_URL must use ws:// or wss://, got '${parsed.protocol}'.`
    );
  }

  // After normalization the path should be stripped. Only warn, never throw —
  // _normalizeWsBase already strips path to bare origin.
  if (parsed.pathname && parsed.pathname !== "/") {
    console.warn(
      `[next.config] NEXT_PUBLIC_WS_BASE_URL had unexpected path '${parsed.pathname}'. ` +
      "Path was stripped; using bare origin only."
    );
  }

  const host = (parsed.hostname || "").toLowerCase();
  if (host.includes("vercel.app") || host.includes("vercel.com")) {
    throw new Error(
      "[next.config] NEXT_PUBLIC_WS_BASE_URL must target backend/Railway origin directly, not Vercel domain."
    );
  }

  if (protectedDeploy && host !== "localhost" && !host.includes("railway.app")) {
    // Warn but don't throw — backend may be hosted on Render, Fly.io, or custom domain.
    console.warn(
      "[next.config] NEXT_PUBLIC_WS_BASE_URL is not a *.railway.app domain. " +
      "Make sure it points to your actual backend WebSocket origin."
    );
  }
}

const isProtectedDeployment = _isProtectedDeployment();

// Read backend URL from all possible env var names across different platforms:
//   INTERNAL_API_URL          — Vercel (set manually in project vars, server-only)
//   NEXT_PUBLIC_API_BASE_URL  — Vercel/v0 (public, set manually in project vars)
//   API_BASE_URL              — Railway (set in railway service vars)
//   API_DOMAIN                — Railway (alternative domain var in railway)
//
// NOTE: NEXT_PUBLIC_* vars are also available server-side in next.config.js
// because this file runs in Node.js during the build & dev server startup,
// where all process.env vars (including NEXT_PUBLIC_*) are accessible.
const rawApiBase =
  process.env.INTERNAL_API_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  process.env.API_BASE_URL ||
  (process.env.API_DOMAIN
    ? `https://${process.env.API_DOMAIN}`
    : "") ||
  "";

// Log the resolved base for debugging (only in dev or when env vars are set)
if (rawApiBase) {
  console.log("[next.config] Resolved API base from env:", rawApiBase.replace(/^(https?:\/\/[^/]+).*$/, "$1***"));
}

// Warn loudly in production when env vars are missing.
// Protected deployments (main/prod) are fail-fast to avoid shipping placeholders.
// Non-protected deployments can continue with warnings for preview/debug workflows.
if (isProd && !rawApiBase) {
  const message =
    "[next.config] Missing INTERNAL_API_URL or NEXT_PUBLIC_API_BASE_URL in production. " +
    "All API rewrites will route to a placeholder and will NOT work. " +
    "Set this in Vercel/Railway env vars before deploying.";
  if (isProtectedDeployment) {
    throw new Error(`${message} Protected deployment is fail-fast by policy.`);
  }
  console.error(`[next.config] WARNING: ${message}`);
}

// Fallback — localhost for local dev, placeholder for production without env vars.
const resolvedBase = rawApiBase || "http://localhost:8000";

// Normalize: strip trailing slash and any accidental /api suffix to prevent
// double-prefix (/api/api/...) when combined with rewrite destinations.
const apiBase = resolvedBase.replace(/\/+$/, "").replace(/\/api$/, "");

const configuredWsBase = _normalizeWsBase(process.env.NEXT_PUBLIC_WS_BASE_URL || "");
const wsBase = configuredWsBase || _normalizeWsBase(apiBase.replace(/^https:\/\//, "wss://").replace(/^http:\/\//, "ws://"));

_validateWsBase(wsBase, {
  protectedDeploy: isProtectedDeployment,
  explicitlyConfigured: Boolean(configuredWsBase),
});

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Expose the resolved backend URL to the client bundle so NEXT_PUBLIC_
  // env var checks in DataStreamDiagnostic / runtimeHealth work correctly
  // even when the user only set API_BASE_URL on Railway.
  env: {
    NEXT_PUBLIC_API_BASE_URL: apiBase,
    NEXT_PUBLIC_WS_BASE_URL: wsBase,
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
              "font-src 'self' https://fonts.gstatic.com",
              "connect-src 'self' wss://*.railway.app https://*.railway.app wss://*.vercel.app https://*.vercel.app https://vitals.vercel-insights.com https://*.vercel-scripts.com",
              "img-src 'self' data:",
              "script-src 'self' 'unsafe-eval' 'unsafe-inline' https://va.vercel-scripts.com",
              "worker-src 'self' blob:",
            ].join("; "),
          },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          // Disable Vercel Toolbar injection in production
          { key: "X-Vercel-Skip-Toolbar", value: "1" },
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
      // /preferences — legacy rewrite kept for any remaining callers;
      // preferencesService now calls /api/v1/config/profile/* directly.
      {
        source: "/preferences",
        destination: `${apiBase}/api/v1/config/profile/effective`,
      },
      {
        source: "/preferences/:path*",
        destination: `${apiBase}/api/v1/config/profile/:path*`,
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
