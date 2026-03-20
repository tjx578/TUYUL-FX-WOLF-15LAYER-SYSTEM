import { NextRequest, NextResponse } from "next/server";

const COOKIE_NAME = "wolf15_session";
const MAX_AGE = 60 * 60 * 8; // 8 hours

// Simple in-memory rate limiter: max 10 requests per 60s per IP
const RATE_WINDOW_MS = 60_000;
const RATE_MAX = 10;
const rateBuckets = new Map<string, { count: number; resetAt: number }>();

function isRateLimited(ip: string): boolean {
  const now = Date.now();
  const bucket = rateBuckets.get(ip);
  if (!bucket || now >= bucket.resetAt) {
    rateBuckets.set(ip, { count: 1, resetAt: now + RATE_WINDOW_MS });
    return false;
  }
  bucket.count++;
  return bucket.count > RATE_MAX;
}

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
  const ip = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ?? "unknown";
  if (isRateLimited(ip)) {
    return NextResponse.json({ error: "too many requests" }, { status: 429 });
  }

  const contentLength = parseInt(request.headers.get("content-length") ?? "0", 10);
  if (contentLength > 8192) {
    return NextResponse.json({ error: "payload too large" }, { status: 413 });
  }

  const body = await request.json().catch(() => ({})) as { token?: string };
  const token = body.token?.trim();

  if (!token || token.length < 10 || token.length > 4096) {
    return NextResponse.json({ error: "invalid token" }, { status: 400 });
  }

  // Validate JWT structure (header.payload.signature)
  const parts = token.split(".");
  if (parts.length !== 3) {
    return NextResponse.json({ error: "malformed token" }, { status: 400 });
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
