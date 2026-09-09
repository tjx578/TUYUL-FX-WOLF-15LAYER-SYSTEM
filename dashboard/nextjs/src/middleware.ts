import { NextRequest, NextResponse } from "next/server";

/**
 * Next.js Edge Middleware — single active middleware (src/ layout).
 *
 * Concern separation:
 *   1. AUTH RESOLUTION — read session cookie, nothing more.
 *   2. PROXY HEADER INJECTION — attach resolved token to outgoing
 *      proxy requests so secrets stay out of the client JS bundle.
 *      This injection is surface-agnostic: it applies whether the
 *      proxy routes to core-api or to the optional dashboard-BFF.
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

async function isValidatedSession(token: string): Promise<boolean> {
    if (token.split(".").length !== 3) return false;
    const origin = (process.env.INTERNAL_API_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/+$/, "");
    if (!origin) return false;
    try {
        const response = await fetch(`${origin}/api/auth/session`, {
            headers: { authorization: `Bearer ${token}`, accept: "application/json" },
            cache: "no-store",
        });
        return response.ok;
    } catch {
        return false;
    }
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
export async function middleware(request: NextRequest): Promise<NextResponse> {
    const { pathname } = request.nextUrl;

    // Auth resolution — always runs, never redirects.
    const token = resolveSessionToken(request);

    // Proxy routes: inject auth header from resolved token.
    if (pathname.startsWith(PROXY_PREFIX)) {
        if (!token || !(await isValidatedSession(token))) {
            return NextResponse.json(
                { error: "Unauthorized", code: "SESSION_REQUIRED" },
                { status: 401, headers: { "cache-control": "no-store" } },
            );
        }
        return injectProxyAuth(request, token);
    }

    const publicPath = pathname === "/login" || pathname.startsWith("/api/auth/") || pathname === "/api/set-session";
    if (!publicPath && (!token || !(await isValidatedSession(token)))) {
        return NextResponse.json(
            { error: "Unauthorized", code: "SESSION_REQUIRED" },
            { status: 401, headers: { "cache-control": "no-store" } },
        );
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
