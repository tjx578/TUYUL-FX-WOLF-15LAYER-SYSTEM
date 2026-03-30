import { NextRequest, NextResponse } from "next/server";

/**
 * GET /api/auth/ws-ticket
 *
 * Returns a session-cookie-based auth token for WebSocket connections.
 * The session cookie is set server-side by /api/set-session after the
 * owner-session flow — neither raw API keys nor secrets are exposed
 * in the client JS bundle.
 *
 * Auth model: owner-only.
 *   - If a valid session cookie exists, return it.
 *   - If no session cookie but DASHBOARD_MODE=owner and API_KEY are set,
 *     auto-bootstrap the session by setting the cookie and returning the
 *     token.  This handles the first-visit case where no login flow has
 *     run yet.
 *   - Otherwise return 401.
 *
 * See docs/architecture/dashboard-control-surface.md — Auth Model.
 */

const SESSION_COOKIE = "wolf15_session";
const MAX_AGE = 60 * 60 * 8; // 8 hours

export async function GET(request: NextRequest): Promise<NextResponse> {
    // 1. Existing session cookie — fast path.
    const sessionToken = request.cookies.get(SESSION_COOKIE)?.value?.trim();
    if (sessionToken) {
        return NextResponse.json({ token: sessionToken });
    }

    // 2. Owner-mode auto-bootstrap: set session cookie from server-side API_KEY.
    //    API_KEY is a server-only env var (no NEXT_PUBLIC_ prefix) so it is
    //    never included in the client JS bundle.
    const dashboardMode = (process.env.DASHBOARD_MODE ?? "").trim().toLowerCase();
    const apiKey = (process.env.API_KEY ?? "").trim();
    if (dashboardMode === "owner" && apiKey) {
        const response = NextResponse.json({ token: apiKey });
        response.cookies.set(SESSION_COOKIE, apiKey, {
            httpOnly: true,
            secure: process.env.NODE_ENV === "production",
            sameSite: "lax",
            path: "/",
            maxAge: MAX_AGE,
        });
        return response;
    }

    return NextResponse.json(
        { error: "no session — authenticate via /api/auth/owner-session first" },
        { status: 401 },
    );
}
