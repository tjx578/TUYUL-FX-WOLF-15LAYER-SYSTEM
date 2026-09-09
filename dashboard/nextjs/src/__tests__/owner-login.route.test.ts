// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "../app/api/auth/owner-login/route";

const viewerToken = () => `${Buffer.from(JSON.stringify({ alg: "HS256" })).toString("base64url")}.${Buffer.from(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 900 })).toString("base64url")}.synthetic-signature`;

vi.mock("@/lib/serverAuth", () => ({
  validateSessionToken: vi.fn(async (token: string) =>
    token.endsWith(".synthetic-signature") ? { role: "viewer" } : null,
  ),
}));

function request(body: unknown, origin = "https://dashboard.example") {
  return new NextRequest("https://dashboard.example/api/auth/owner-login", {
    method: "POST",
    headers: { "content-type": "application/json", origin },
    body: JSON.stringify(body),
  });
}

describe("owner login session boundary", () => {
  beforeEach(() => {
    vi.stubEnv("DASHBOARD_CANONICAL_ORIGIN", "https://dashboard.example");
    process.env.INTERNAL_API_URL = "https://core.example";
  });

  afterEach(() => {
    delete process.env.INTERNAL_API_URL;
    vi.unstubAllEnvs(); vi.restoreAllMocks();
  });

  it("sets an HttpOnly cookie without returning the JWT", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      Response.json({ token: viewerToken() }),
    );
    const response = await POST(request({ username: "owner", password: "secret" }));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ ok: true });
    const cookie = response.headers.get("set-cookie") ?? "";
    expect(cookie).toContain("wolf15_session=");
    expect(cookie.toLowerCase()).toContain("httponly");
  });

  it("rejects cross-origin login", async () => {
    globalThis.fetch = vi.fn();
    const response = await POST(
      request({ username: "owner", password: "secret" }, "https://evil.example"),
    );
    expect(response.status).toBe(403);
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("maps invalid credentials to a generic response", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response(null, { status: 401 }));
    const response = await POST(request({ username: "owner", password: "wrong" }));
    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ error: "invalid credentials" });
  });

  it("fails closed when the core returns an unauthorized token", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(Response.json({ token: "wrong.token.value" }));
    const response = await POST(request({ username: "owner", password: "secret" }));
    expect(response.status).toBe(503);
    expect(response.headers.get("set-cookie")).toBeNull();
  });
});
