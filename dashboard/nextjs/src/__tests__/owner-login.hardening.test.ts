// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "../app/api/auth/owner-login/route";

const viewer = { user_id: "owner", email: "owner@example.test", role: "viewer", scopes: ["read:dashboard"], auth_method: "jwt" };
function token(seconds = 900, alg = "HS256") {
  const encode = (v: unknown) => Buffer.from(JSON.stringify(v)).toString("base64url");
  return `${encode({ alg })}.${encode({ exp: Math.floor(Date.now() / 1000) + seconds })}.synthetic-signature`;
}
function request(body: unknown = { username: "owner", password: "synthetic-password" }, extra: Record<string, string> = {}) {
  return new NextRequest("https://dashboard.example/api/auth/owner-login", {
    method: "POST", headers: { "content-type": "application/json", origin: "https://dashboard.example", ...extra },
    body: JSON.stringify(body),
  });
}
function upstream(rawToken = token(), session: unknown = viewer) {
  const fetcher = vi.fn().mockResolvedValueOnce(Response.json({ token: rawToken })).mockResolvedValueOnce(Response.json(session));
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}
describe("owner login hardening with real session validator", () => {
  beforeEach(() => {
    vi.stubEnv("DASHBOARD_CANONICAL_ORIGIN", "https://dashboard.example");
    vi.stubEnv("INTERNAL_API_URL", "https://core.example");
    vi.stubEnv("NODE_ENV", "production");
  });
  afterEach(() => {
    vi.useRealTimers(); vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.restoreAllMocks();
  });
  it("validates viewer scope, uses bounded transport, and issues only a secure cookie", async () => {
    const rawToken = token();
    const fetcher = upstream(rawToken);
    const response = await POST(request());
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ ok: true });
    const cookie = response.cookies.get("wolf15_session");
    expect(cookie).toMatchObject({ value: rawToken, httpOnly: true, secure: true, sameSite: "lax", path: "/" });
    expect(cookie!.maxAge).toBeGreaterThan(895);
    expect(cookie!.maxAge).toBeLessThanOrEqual(900);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(fetcher).toHaveBeenCalledTimes(2);
    for (const [, options] of fetcher.mock.calls) {
      expect(options.redirect).toBe("error"); expect(options.signal).toBeInstanceOf(AbortSignal);
    }
  });
  it.each(["https://evil.example", "", "null"])("rejects origin %s", async origin => {
    const fetcher = upstream();
    expect((await POST(request(undefined, { origin }))).status).toBe(403);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it.each([401, 429, 500, 302])("fails closed on upstream status %s", async status => {
    const fetcher = vi.fn().mockResolvedValue(new Response(null, { status }));
    vi.stubGlobal("fetch", fetcher);
    const response = await POST(request());
    expect(response.status).toBe(status === 401 || status === 429 ? status : 503);
    expect(response.headers.get("set-cookie")).toBeNull();
    if (status === 429) expect(response.headers.get("retry-after")).toBe("60");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it.each([{ ...viewer, role: "operator" }, { ...viewer, scopes: [] }, { ...viewer, auth_method: "api_key" }, null])("rejects unauthorized core session", async session => {
    upstream(token(), session);
    const response = await POST(request());
    expect(response.status).toBe(503); expect(response.headers.get("set-cookie")).toBeNull();
  });
  it.each([-10, 0])("rejects expired token (%s)", async seconds => {
    const fetcher = upstream(token(seconds));
    expect((await POST(request())).status).toBe(503); expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("rejects a non-HS256 token", async () => {
    upstream(token(900, "none")); expect((await POST(request())).status).toBe(503);
  });
  it("caps cookie at remaining verified lifetime", async () => {
    upstream(token(45));
    const response = await POST(request());
    expect(response.status).toBe(200);
    expect(response.cookies.get("wolf15_session")!.maxAge).toBeLessThanOrEqual(45);
    expect(response.cookies.get("wolf15_session")!.maxAge).toBeGreaterThan(40);
  });
  it.each([{}, { "content-length": "1" }] as Record<string, string>[])("bounds real body bytes even without honest Content-Length", async headers => {
    const fetcher = upstream();
    expect((await POST(request({ username: "owner", password: "x".repeat(5000) }, headers))).status).toBe(413);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("counts UTF-8 bytes rather than characters", async () => {
    const fetcher = upstream();
    expect((await POST(request({ username: "界".repeat(200), password: "界".repeat(1200) }))).status).toBe(413);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it.each([null, {}, { username: "owner", password: "" }])("rejects invalid credential shape", async body => {
    const fetcher = upstream(); expect((await POST(request(body))).status).toBe(400); expect(fetcher).not.toHaveBeenCalled();
  });
  it("bounds upstream token response", async () => {
    upstream("x".repeat(9000)); expect((await POST(request())).status).toBe(503);
  });
  it("rejects HTTP credential forwarding in production", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://core.internal");
    const fetcher = upstream(); expect((await POST(request())).status).toBe(503); expect(fetcher).not.toHaveBeenCalled();
  });
  it.each([0, 1])("aborts stalled upstream phase %s", async phase => {
    vi.useFakeTimers();
    const fetcher = vi.fn();
    if (phase === 1) fetcher.mockResolvedValueOnce(Response.json({ token: token() }));
    fetcher.mockImplementation((_url, options) => new Promise((_, reject) => {
      options.signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
    }));
    vi.stubGlobal("fetch", fetcher);
    const pending = POST(request()); await vi.advanceTimersByTimeAsync(5001);
    const response = await pending;
    expect(response.status).toBe(503); expect(response.headers.get("set-cookie")).toBeNull();
    expect(fetcher.mock.calls.at(-1)![1].signal.aborted).toBe(true);
  });
  it("times out an unfinished request body", async () => {
    vi.useFakeTimers();
    const cancel = vi.fn();
    const incoming = new NextRequest("https://dashboard.example/api/auth/owner-login", {
      method: "POST", headers: { origin: "https://dashboard.example", "content-type": "application/json" },
      body: new ReadableStream<Uint8Array>({ cancel }), duplex: "half",
    } as NonNullable<ConstructorParameters<typeof NextRequest>[1]>);
    const fetcher = upstream(); const pending = POST(incoming);
    await vi.advanceTimersByTimeAsync(5001);
    expect((await pending).status).toBe(408); expect(cancel).toHaveBeenCalled(); expect(fetcher).not.toHaveBeenCalled();
  });
});
