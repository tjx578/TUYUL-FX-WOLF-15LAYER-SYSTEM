import { NextRequest, NextResponse } from "next/server";

const COOKIE_NAME = "wolf15_session_token";
const MAX_AGE = 60 * 60 * 8; // 8 hours

/**
 * POST /api/set-session
 * Body: { token: string }
 *
 * Sets a first-party HttpOnly cookie on the Vercel domain so that
 * server components can read the auth token on subsequent requests.
 * This is necessary because the Railway backend sets its cookie on
 * its own domain, which the browser blocks as cross-site.
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  const body = await request.json().catch(() => ({})) as { token?: string };
  const token = body.token?.trim();

  if (!token) {
    return NextResponse.json({ error: "token required" }, { status: 400 });
  }

  const response = NextResponse.json({ ok: true });
  response.cookies.set(COOKIE_NAME, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: MAX_AGE,
  });

  return response;
}

/**
 * DELETE /api/set-session
 * Clears the session cookie (logout).
 */
export async function DELETE(): Promise<NextResponse> {
  const response = NextResponse.json({ ok: true });
  response.cookies.delete(COOKIE_NAME);
  return response;
}
