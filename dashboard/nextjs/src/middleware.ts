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
const ROLE_HEADER = "x-user-role";
const ADMIN_ROLES = new Set(["risk_admin", "config_admin", "approver"]);
const ADMIN_PATHS = ["/audit"];

// Proxy route prefixes that are rewritten to the backend by next.config.js.
// These MUST NOT be auth-checked by the middleware (no redirect).
const PROXY_PREFIXES = [
    "/api/",
    "/health",
    "/auth/",
    "/preferences",
    "/pipeline/",
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
function handlePageRoute(request: NextRequest): NextResponse {
    const { pathname } = request.nextUrl;

    // /login is always accessible
    if (pathname.startsWith("/login")) {
        return NextResponse.next();
    }

    const sessionCookie = request.cookies.get(SESSION_COOKIE)?.value;

    // Redirect unauthenticated requests to /login
    if (!sessionCookie) {
        const loginUrl = new URL("/login", request.url);
        loginUrl.searchParams.set("callbackUrl", pathname);
        return NextResponse.redirect(loginUrl, 307);
    }

    // Admin-only paths require an admin role header
    const isAdminPath = ADMIN_PATHS.some((p) => pathname.startsWith(p));
    if (isAdminPath) {
        const role = request.headers.get(ROLE_HEADER);
        if (!role || !ADMIN_ROLES.has(role)) {
            const loginUrl = new URL("/login", request.url);
            loginUrl.searchParams.set("callbackUrl", pathname);
            return NextResponse.redirect(loginUrl, 307);
        }
    }

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
         * Match ALL request paths EXCEPT static assets:
         *   _next/static  — JS/CSS chunks
         *   _next/image   — optimised images
         *   favicon.ico   — browser icon
         *
         * Inside the function, proxy routes vs page routes are split
         * so that proxy routes get auth-injection and page routes
         * get session-guard redirects.
         */
        "/((?!_next/static|_next/image|favicon\\.ico).*)",
    ],
};
