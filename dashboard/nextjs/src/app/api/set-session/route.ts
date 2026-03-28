import { NextRequest, NextResponse } from "next/server";

const COOKIE_NAME = "wolf15_session";
const MAX_AGE = 60 * 60 * 8; // 8 hours

// Simple in-memory rate limiter: max 10 requests per 60s per IP.
// SEC-02 NOTE: This is best-effort only in serverless deployments (Vercel).
// Each cold start resets the Map. For production hardening, replace with
// an external atomic counter (Upstash Redis + @upstash/ratelimit, or
// Vercel KV). For a single-owner private dashboard this is acceptable.
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
    return NextResponse.json({ error: "must have 3 dot-separated segments" }, { status: 400 });
  }

  // Each segment must be at least 10 chars of valid base64url
  const base64urlRe = /^[A-Za-z0-9_-]{10,}$/;
  if (!base64urlRe.test(parts[0])) {
    return NextResponse.json({ error: "invalid header segment" }, { status: 400 });
  }
  if (!base64urlRe.test(parts[1])) {
    return NextResponse.json({ error: "invalid payload segment" }, { status: 400 });
  }
  if (!base64urlRe.test(parts[2])) {
    return NextResponse.json({ error: "invalid signature segment" }, { status: 400 });
  }

  // Decode and validate header — must have "alg" field
  try {
    const header = JSON.parse(Buffer.from(parts[0], "base64url").toString());
    if (!header || typeof header !== "object" || !header.alg) {
      return NextResponse.json({ error: "header missing alg field" }, { status: 400 });
    }
  } catch {
    return NextResponse.json({ error: "invalid header encoding" }, { status: 400 });
  }

  // Decode and validate payload — must be a JSON object
  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(Buffer.from(parts[1], "base64url").toString());
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      return NextResponse.json({ error: "payload must be a JSON object" }, { status: 400 });
    }
  } catch {
    return NextResponse.json({ error: "invalid payload encoding" }, { status: 400 });
  }

  // Check expiry if present
  if (typeof payload.exp === "number" && payload.exp * 1000 < Date.now()) {
    return NextResponse.json({ error: "token expired" }, { status: 400 });
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
