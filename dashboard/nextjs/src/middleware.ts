import { NextRequest, NextResponse } from "next/server";

/**
 * Next.js Edge Middleware — single active middleware (src/ layout).
 *
 * Concern separation:
 *   1. AUTH RESOLUTION — read session cookie, nothing more.
 *   2. PROXY HEADER INJECTION — attach resolved token to outgoing
 *      proxy requests so secrets stay out of the client JS bundle.
 *   3. PAGE ROUTING — owner-only dashboard, no redirect guards.
 *
 * These concerns are kept as pure functions called from the
 * entrypoint — auth never decides routing, and proxy injection
 * never decides auth validity.
 */

// ── 1. Auth resolution ─────────────────────────────────────────────────
// Pure: reads session cookie, returns token or null.  No side-effects,
// no redirects, no fallback to API_KEY (removed in P3).

const SESSION_COOKIE = "wolf15_session";

function resolveSessionToken(request: NextRequest): string | null {
    return request.cookies.get(SESSION_COOKIE)?.value?.trim() || null;
}

// ── 2. Owner-mode auto-bootstrap ───────────────────────────────────────
// In owner mode, if no session cookie exists but the server-side API_KEY
// is configured, auto-set the session cookie so the proxy can inject auth
// without requiring a manual /login visit first.

const COOKIE_MAX_AGE = 60 * 60 * 8; // 8 hours

function ownerAutoBootstrap(
    request: NextRequest,
    response: NextResponse,
): string | null {
    const mode = (process.env.DASHBOARD_MODE ?? "").trim().toLowerCase();
    const apiKey = (process.env.API_KEY ?? "").trim();
    if (mode !== "owner" || !apiKey) return null;

    // Set the session cookie for subsequent requests.
    response.cookies.set(SESSION_COOKIE, apiKey, {
        httpOnly: true,
        secure: process.env.NODE_ENV === "production",
        sameSite: "lax",
        path: "/",
        maxAge: COOKIE_MAX_AGE,
    });
    return apiKey;
}

// ── 3. Proxy header injection ──────────────────────────────────────────
// Injects Authorization header into /api/proxy/* requests when
// the client hasn't already provided one.  Backend decides 401.

const PROXY_PREFIX = "/api/proxy/";

function injectProxyAuth(
    request: NextRequest,
    token: string | null,
): NextResponse {
    if (request.headers.get("authorization")) {
        return NextResponse.next();
    }
    if (token) {
        const headers = new Headers(request.headers);
        headers.set("authorization", `Bearer ${token}`);
        return NextResponse.next({ request: { headers } });
    }
    return NextResponse.next();
}

// ── 4. Entrypoint ──────────────────────────────────────────────────────
export function middleware(request: NextRequest): NextResponse {
    const { pathname } = request.nextUrl;

    // Auth resolution — always runs, never redirects.
    let token = resolveSessionToken(request);

    // Proxy routes: inject auth header from resolved token.
    if (pathname.startsWith(PROXY_PREFIX)) {
        // If no session cookie, try owner-mode auto-bootstrap.
        if (!token) {
            const response = injectProxyAuth(request, null);
            const bootstrapped = ownerAutoBootstrap(request, response);
            if (bootstrapped) {
                // Inject auth into THIS request and set cookie for future ones.
                const headers = new Headers(request.headers);
                headers.set("authorization", `Bearer ${bootstrapped}`);
                const authedResponse = NextResponse.next({ request: { headers } });
                // Copy the cookie from bootstrap into the authed response.
                authedResponse.cookies.set(SESSION_COOKIE, bootstrapped, {
                    httpOnly: true,
                    secure: process.env.NODE_ENV === "production",
                    sameSite: "lax",
                    path: "/",
                    maxAge: COOKIE_MAX_AGE,
                });
                return authedResponse;
            }
        }
        return injectProxyAuth(request, token);
    }

    // Non-proxy page requests: auto-bootstrap cookie if missing.
    if (!token) {
        const response = NextResponse.next();
        ownerAutoBootstrap(request, response);
        return response;
    }

    // All other routes (pages, internal API): pass through.
    // Owner-only dashboard — no login gates, no redirect loops.
    return NextResponse.next();
}

export const config = {
    matcher: [
        /*
         * Match ALL routes EXCEPT static assets:
         *   /_next/static   — JS/CSS chunks
         *   /_next/image    — optimised images
         *   /favicon.ico    — browser icon
         *
         * /api/proxy/* IS matched for auth-header injection.
         */
        "/((?!_next/|favicon\\.ico).*)",
    ],
};
