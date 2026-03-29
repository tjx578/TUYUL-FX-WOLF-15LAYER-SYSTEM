import { NextRequest, NextResponse } from "next/server";

/**
 * Next.js Edge Middleware — Auth-header injection for the runtime proxy.
 *
 * P4 consolidation: all backend REST traffic flows through the single
 * runtime proxy at /api/proxy/[...path]. This middleware injects the
 * session cookie as an Authorization header so secrets stay out of
 * the client JS bundle.
 *
 * Path handling:
 *
 * A) PROXY ROUTE (/api/proxy/*):
 *    Inject Authorization header from session cookie.
 *    Never redirect — backend decides auth failures.
 *
 * B) INTERNAL API ROUTES (/api/auth/*, /api/set-session):
 *    Pass through — these Next.js route handlers manage their own auth.
 *
 * C) PAGE ROUTES (everything else):
 *    Owner mode — pass through without guards.
 */

const SESSION_COOKIE = "wolf15_session";

// Only the runtime proxy prefix needs auth-header injection.
// Build-time rewrites have been removed (P4) — /api/proxy is the single path.
const PROXY_PREFIX = "/api/proxy/";

function isProxyRoute(pathname: string): boolean {
    return pathname.startsWith(PROXY_PREFIX);
}

// ── A) Auth-header injection for proxy routes ──────────────────────────
function handleProxyRoute(request: NextRequest): NextResponse {
    // If the client already sends an Authorization header, pass through
    if (request.headers.get("authorization")) {
        return NextResponse.next();
    }

    // Session cookie → Authorization header injection.
    // API_KEY fallback removed (P3): machine keys must not silently
    // authenticate browser requests.  Owner must have a session cookie
    // from the /api/auth/owner-session flow.
    const sessionToken = request.cookies.get(SESSION_COOKIE)?.value?.trim();
    if (sessionToken) {
        const headers = new Headers(request.headers);
        headers.set("authorization", `Bearer ${sessionToken}`);
        return NextResponse.next({ request: { headers } });
    }

    // No session cookie and no client header → pass through unauthenticated.
    // Backend will return 401; frontend should redirect to owner-session init.
    return NextResponse.next();
}

// ── B/C) Page routes — owner mode, no guard ────────────────────────────
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
         * The runtime proxy (/api/proxy/*) IS matched so handleProxyRoute()
         * can inject Authorization headers from the session cookie.
         */
        "/((?!login|_next/|favicon\\.ico).*)",
    ],
};
