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
 *   - The API_KEY fallback has been REMOVED (P3).
 *   - Returning a raw machine API key to the browser violates the
 *     dashboard-control-surface auth contract: "browser-facing API key
 *     fallback is NOT allowed".
 *   - If no session cookie is present, the caller gets 401.
 *
 * See docs/architecture/dashboard-control-surface.md — Auth Model.
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
    // Session cookie (set by /api/set-session after owner-session flow)
    const sessionToken = request.cookies.get("wolf15_session")?.value?.trim();
    if (sessionToken) {
        return NextResponse.json({ token: sessionToken });
    }

    return NextResponse.json(
        { error: "no session — authenticate via /api/auth/owner-session first" },
        { status: 401 },
    );
}
