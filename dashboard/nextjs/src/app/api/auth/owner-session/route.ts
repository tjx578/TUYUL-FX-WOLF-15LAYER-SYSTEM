import { NextRequest, NextResponse } from "next/server";

/**
 * GET /api/auth/owner-session
 *
 * Owner-mode session bootstrap.  When DASHBOARD_MODE=owner and a
 * server-side API_KEY is configured, sets the wolf15_session cookie
 * and redirects to "/".
 *
 * This exists because Server Components cannot modify cookies in
 * Next.js 15 — only Route Handlers and Server Actions can.  The
 * login page redirects here instead of calling cookies().set().
 */

const SESSION_COOKIE = "wolf15_session";
const MAX_AGE = 60 * 60 * 8; // 8 hours

export async function GET(request: NextRequest): Promise<NextResponse> {
    const dashboardMode = (process.env.DASHBOARD_MODE ?? "").trim().toLowerCase();
    const apiKey = (process.env.API_KEY ?? "").trim();

    if (dashboardMode !== "owner" || !apiKey) {
        return NextResponse.json(
            { error: "owner-session requires DASHBOARD_MODE=owner and API_KEY" },
            { status: 403 },
        );
    }

    const redirectUrl = new URL("/", request.url);
    const response = NextResponse.redirect(redirectUrl, 302);

    response.cookies.set(SESSION_COOKIE, apiKey, {
        httpOnly: true,
        secure: process.env.NODE_ENV === "production",
        sameSite: "lax",
        path: "/",
        maxAge: MAX_AGE,
    });

    return response;
}
