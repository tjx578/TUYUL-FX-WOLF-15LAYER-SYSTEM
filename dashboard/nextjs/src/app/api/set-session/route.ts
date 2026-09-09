import { NextRequest, NextResponse } from "next/server";
import { validateSessionToken } from "@/lib/serverAuth";

const COOKIE_NAME = "wolf15_session";
const MAX_AGE = 60 * 60 * 8;
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
  bucket.count += 1;
  return bucket.count > RATE_MAX;
}

function jsonError(error: string, status: number): NextResponse {
  return NextResponse.json(
    { error },
    { status, headers: { "cache-control": "no-store" } },
  );
}

/**
 * Establish a same-origin browser session from an already-issued viewer JWT.
 * Machine API keys and non-viewer JWTs are rejected by validateSessionToken().
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  const ip =
    request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ?? "unknown";
  if (isRateLimited(ip)) return jsonError("too many requests", 429);

  const contentLength = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(contentLength) && contentLength > 8192) {
    return jsonError("payload too large", 413);
  }

  const body = (await request.json().catch(() => ({}))) as { token?: unknown };
  const token = typeof body.token === "string" ? body.token.trim() : "";

  if (!token || token.length < 10 || token.length > 4096) {
    return jsonError("invalid token", 400);
  }

  const parts = token.split(".");
  if (parts.length !== 3) return jsonError("invalid token", 400);

  const base64url = /^[A-Za-z0-9_-]{10,}$/;
  if (!parts.every((part) => base64url.test(part))) {
    return jsonError("invalid token", 400);
  }

  let expiresAt: number;
  try {
    const header = JSON.parse(
      Buffer.from(parts[0], "base64url").toString(),
    ) as Record<string, unknown>;
    if (header.alg !== "HS256" || header.typ !== "JWT") {
      return jsonError("invalid token", 400);
    }

    const payload = JSON.parse(
      Buffer.from(parts[1], "base64url").toString(),
    ) as Record<string, unknown>;
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      return jsonError("invalid token", 400);
    }

    expiresAt = Number(payload.exp);
    const now = Math.floor(Date.now() / 1000);
    if (!Number.isFinite(expiresAt) || expiresAt <= now) {
      return jsonError("expired token", 400);
    }
  } catch {
    return jsonError("invalid token", 400);
  }

  const viewer = await validateSessionToken(token);
  if (!viewer) {
    return jsonError("viewer authorization required", 403);
  }

  const now = Math.floor(Date.now() / 1000);
  const cookieMaxAge = Math.max(1, Math.min(MAX_AGE, expiresAt - now));
  const response = NextResponse.json(
    { ok: true },
    { headers: { "cache-control": "no-store" } },
  );
  response.cookies.set(COOKIE_NAME, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: cookieMaxAge,
  });
  return response;
}

export async function DELETE(): Promise<NextResponse> {
  const response = NextResponse.json(
    { ok: true },
    { headers: { "cache-control": "no-store" } },
  );
  response.cookies.delete(COOKIE_NAME);
  return response;
}
