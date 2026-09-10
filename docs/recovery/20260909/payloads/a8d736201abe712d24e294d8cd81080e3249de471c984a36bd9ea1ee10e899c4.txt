import { NextRequest, NextResponse } from "next/server";
import { validateSessionToken } from "@/lib/serverAuth";

/**
 * GET /api/auth/ws-ticket
 *
 * Returns a session-cookie-based auth token for WebSocket connections.
 * The session cookie is set by /api/set-session only after backend validation.
 *
 * Auth model: owner-only.
 *   - If a valid session cookie exists, return it.
 *   - Invalid or missing sessions return 401; there is no auto-bootstrap.
 *
 * See docs/architecture/dashboard-control-surface.md — Auth Model.
 */

const SESSION_COOKIE = "wolf15_session";
export async function GET(request: NextRequest): Promise<NextResponse> {
    const sessionToken = request.cookies.get(SESSION_COOKIE)?.value?.trim();
    if (sessionToken && await validateSessionToken(sessionToken)) {
        return NextResponse.json({ token: sessionToken });
    }

    return NextResponse.json(
        { error: "validated session required" },
        { status: 401 },
    );
}
