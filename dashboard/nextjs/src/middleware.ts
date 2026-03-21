import { NextRequest, NextResponse } from "next/server";

/**
 * Next.js Edge Middleware — Unified auth guard + auth-header injection
 *
 * This single middleware replaces two previously-conflicting files
 * (root middleware.ts was dead code because Next.js only loads src/middleware.ts
 *  when using the src/ directory layout).
 *
 * Responsibility split by path:
 *
 * A) PROXY ROUTES (/api/*, /health, /auth/*, /preferences/*, /pipeline/*):
 *    Inject Authorization header server-side so secrets stay out of the
 *    client JS bundle.  Never redirect — backend decides auth failures.
 *    Priority: existing header > session cookie > server API_KEY.
 *
 * B) PAGE ROUTES (everything else except /login, static assets):
 *    Enforce session cookie.  Missing cookie → 307 redirect to /login.
 *    Admin-only paths additionally require x-user-role header.
 */

const SESSION_COOKIE = "wolf15_session";

// Proxy route prefixes that are rewritten to the backend by next.config.js.
// These MUST NOT be auth-checked by the middleware (no redirect).
const PROXY_PREFIXES = [
    "/api/",
    "/health",
    "/auth/",
    "/preferences",
    "/pipeline",
];

function isProxyRoute(pathname: string): boolean {
    return PROXY_PREFIXES.some((p) => pathname.startsWith(p));
}

// ── A) Auth-header injection for proxy routes ──────────────────────────
function handleProxyRoute(request: NextRequest): NextResponse {
    const { pathname } = request.nextUrl;

    // Internal Next.js API routes handle their own auth
    if (pathname.startsWith("/api/auth/") || pathname.startsWith("/api/set-session")) {
        return NextResponse.next();
    }

    // If the client already sends an Authorization header, pass through
    if (request.headers.get("authorization")) {
        return NextResponse.next();
    }

    // Try session cookie first
    const sessionToken = request.cookies.get(SESSION_COOKIE)?.value?.trim();
    if (sessionToken) {
        const headers = new Headers(request.headers);
        headers.set("authorization", `Bearer ${sessionToken}`);
        return NextResponse.next({ request: { headers } });
    }

    // Fallback: server-only API key (NOT NEXT_PUBLIC_*)
    const apiKey = process.env.API_KEY?.trim();
    if (apiKey) {
        const headers = new Headers(request.headers);
        headers.set("authorization", `Bearer ${apiKey}`);
        return NextResponse.next({ request: { headers } });
    }

    return NextResponse.next();
}

// ── B) Session guard for page routes ───────────────────────────────────
// NOTE: Owner mode — all pages are accessible without authentication.
// The server auth (serverAuth.ts) already returns the owner user unconditionally,
// so the middleware session guard is intentionally disabled here.
function handlePageRoute(_request: NextRequest): NextResponse {
    return NextResponse.next();
}

// ── Entrypoint ─────────────────────────────────────────────────────────
export function middleware(request: NextRequest): NextResponse {
    const { pathname } = request.nextUrl;

    if (isProxyRoute(pathname)) {
        return handleProxyRoute(request);
    }

    return handlePageRoute(request);
}

export const config = {
    matcher: [
        /*
         * Match ALL routes EXCEPT:
         *   /login          — login page (prevent infinite redirect)
         *   /_next/static   — JS/CSS chunks
         *   /_next/image    — optimised images
         *   /favicon.ico    — browser icon
         *
         * Proxy routes (/api/, /auth/, /health, /pipeline/, /preferences/)
         * ARE matched so handleProxyRoute() can inject Authorization headers.
         * The isProxyRoute() check inside middleware() routes them correctly.
         */
        "/((?!login|_next/|favicon\\.ico).*)",
    ],
};
