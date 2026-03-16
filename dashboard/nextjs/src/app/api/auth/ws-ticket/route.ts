import { NextRequest, NextResponse } from "next/server";

/**
 * GET /api/auth/ws-ticket
 *
 * Returns an auth token for WebSocket connections.
 * Reads the session cookie first, then falls back to the server-only
 * API_KEY env var. Neither value is exposed in the client JS bundle.
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
    // 1. Prefer session cookie (set by /api/set-session after login)
    const sessionToken = request.cookies.get("wolf15_session")?.value?.trim();
    if (sessionToken) {
        return NextResponse.json({ token: sessionToken });
    }

    // 2. Fallback: server-only API key (NOT NEXT_PUBLIC_*)
    const apiKey = process.env.API_KEY?.trim();
    if (apiKey) {
        return NextResponse.json({ token: apiKey });
    }

    return NextResponse.json(
        { error: "no auth configured" },
        { status: 401 },
    );
}
