import { NextResponse } from "next/server";

/**
 * GET /api/auth/owner-session
 *
 * Retired owner auto-bootstrap endpoint. Machine credentials must never be
 * converted into a browser session, so this route always fails closed.
 */

export async function GET(): Promise<NextResponse> {
    return NextResponse.json(
        { error: "Owner auto-bootstrap is disabled; a validated user session is required" },
        { status: 403, headers: { "cache-control": "no-store" } },
    );
}
