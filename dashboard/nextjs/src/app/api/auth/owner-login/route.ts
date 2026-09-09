import { NextRequest, NextResponse } from "next/server";
import { getCoreApiUrl } from "@/lib/server/dashboardTopology";
import { validateSessionToken } from "@/lib/serverAuth";
import { checkCanonicalOrigin } from "@/lib/server/canonicalOrigin";

const COOKIE_NAME = "wolf15_session";
const MAX_AGE = 15 * 60;

class BodyLimitError extends Error {}

// Bound real streamed bytes, not the caller's Content-Length declaration.
async function readJson(body: ReadableStream<Uint8Array> | null, limit: number, signal: AbortSignal): Promise<unknown> {
  if (!body) throw new Error("missing body");
  const reader = body.getReader();
  let rejectAbort: (() => void) | undefined;
  const aborted = new Promise<never>((_, reject) => {
    rejectAbort = () => reject(new Error("deadline exceeded"));
    signal.addEventListener("abort", rejectAbort, { once: true });
  });
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    if (signal.aborted) throw new Error("deadline exceeded");
    for (;;) {
      const { done, value } = await Promise.race([reader.read(), aborted]);
      if (done) break;
      size += value.byteLength;
      if (size > limit) throw new BodyLimitError();
      chunks.push(value);
    }
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } finally {
    if (rejectAbort) signal.removeEventListener("abort", rejectAbort);
    void reader.cancel().catch(() => undefined);
  }
}

function remainingLifetime(token: string): number {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return 0;
    const header = JSON.parse(Buffer.from(parts[0], "base64url").toString("utf8"));
    const payload = JSON.parse(Buffer.from(parts[1], "base64url").toString("utf8"));
    if (header.alg !== "HS256" || !Number.isSafeInteger(payload.exp)) return 0;
    return Math.max(0, Math.min(MAX_AGE, payload.exp - Math.floor(Date.now() / 1000)));
  } catch {
    return 0;
  }
}

function error(status: number): NextResponse {
  return NextResponse.json(
    { error: status === 401 ? "invalid credentials" : "authentication unavailable" },
    { status, headers: { "cache-control": "no-store", ...(status === 429 ? { "retry-after": "60" } : {}) } },
  );
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const originFailure = checkCanonicalOrigin(request);
  if (originFailure) return error(originFailure);
  if (request.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json") return error(415);
  const length = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(length) && length > 4096) return error(413);

  let body: { username?: unknown; password?: unknown } | null;
  const bodyController = new AbortController();
  const bodyTimer = setTimeout(() => bodyController.abort(), 5000);
  try {
    body = await readJson(request.body, 4096, bodyController.signal) as typeof body;
  } catch (failure) {
    return error(failure instanceof BodyLimitError ? 413 : bodyController.signal.aborted ? 408 : 400);
  } finally {
    clearTimeout(bodyTimer);
  }
  const username = typeof body?.username === "string" ? body.username.trim() : "";
  const password = typeof body?.password === "string" ? body.password : "";
  if (!username || username.length > 254 || !password || password.length > 1024) return error(400);

  const coreApiUrl = getCoreApiUrl();
  if (!coreApiUrl) return error(503);
  try {
    const url = new URL(coreApiUrl);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) return error(503);
    if (process.env.NODE_ENV === "production" && url.protocol !== "https:") return error(503);
  } catch {
    return error(503);
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5000);
  try {
    const upstream = await fetch(coreApiUrl + "/api/auth/owner-login", {
      method: "POST",
      headers: { "content-type": "application/json", accept: "application/json" },
      body: JSON.stringify({ username, password }),
      cache: "no-store",
      redirect: "error",
      signal: controller.signal,
    });
    if (upstream.status === 401) return error(401);
    if (upstream.status === 429) return error(429);
    if (!upstream.ok) return error(503);
    const payload = await readJson(upstream.body, 8192, controller.signal) as { token?: unknown } | null;
    const token = typeof payload?.token === "string" ? payload.token : "";
    if (!token || !remainingLifetime(token) || !(await validateSessionToken(token, controller.signal))) return error(503);
    // Expiry is used only after core signature/session authorization succeeds.
    const maxAge = remainingLifetime(token);
    if (!maxAge || controller.signal.aborted) return error(503);

    const response = NextResponse.json({ ok: true }, { headers: { "cache-control": "no-store" } });
    response.cookies.set(COOKIE_NAME, token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
      maxAge,
    });
    return response;
  } catch {
    return error(503);
  } finally {
    clearTimeout(timer);
  }
}
