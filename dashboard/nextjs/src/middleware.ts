import { NextRequest, NextResponse } from "next/server";

/**
 * Next.js Edge Middleware — Server-side auth injection
 *
 * For proxied REST requests (rewritten to the backend via next.config.js),
 * injects the Authorization header server-side so the API key is never
 * shipped in the client JavaScript bundle.
 *
 * Priority:
 *   1. Existing Authorization header from client (JWT from localStorage)
 *   2. wolf15_session cookie (set by /api/set-session after login)
 *   3. Server-only API_KEY env var (fallback for service-mode access)
 */
export function middleware(request: NextRequest): NextResponse {
    // Don't inject auth on internal Next.js API routes (they handle their own auth)
    if (request.nextUrl.pathname.startsWith("/api/auth/")) {
        return NextResponse.next();
    }
    if (request.nextUrl.pathname.startsWith("/api/set-session")) {
        return NextResponse.next();
    }

    // If the client already sends an Authorization header, pass through
    if (request.headers.get("authorization")) {
        return NextResponse.next();
    }

    // Try session cookie first
    const sessionToken = request.cookies.get("wolf15_session")?.value?.trim();
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

export const config = {
    matcher: [
        "/api/:path*",
        "/health",
        "/auth/:path*",
        "/preferences/:path*",
        "/pipeline/:path*",
    ],
};
