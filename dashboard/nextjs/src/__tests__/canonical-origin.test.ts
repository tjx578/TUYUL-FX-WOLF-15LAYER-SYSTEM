// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "../app/api/auth/owner-login/route";
import { normalizeBrowserOrigin } from "../lib/server/canonicalOrigin";

describe("explicit canonical origin authority", () => {
  beforeEach(() => { vi.stubEnv("NODE_ENV", "production"); vi.stubEnv("DASHBOARD_CANONICAL_ORIGIN", "http://127.0.0.1:3000"); vi.stubGlobal("fetch", vi.fn()); });
  afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });
  const request = (origin: string, extra = {}) => new NextRequest("http://0.0.0.0:3000/api/auth/owner-login", {
    method: "POST", headers: { origin, host: "127.0.0.1:3000", "content-type": "application/json", ...extra }, body: "{}",
  });
  it("reaches body validation with canonical browser origin and wildcard bind", async () => {
    const response = await POST(request("http://127.0.0.1:3000"));
    expect(response.status).toBe(400); expect(response.headers.get("set-cookie")).toBeNull(); expect(fetch).not.toHaveBeenCalled();
  });
  it("uses configured HTTPS public origin through a proxy", async () => {
    vi.stubEnv("DASHBOARD_CANONICAL_ORIGIN", "https://dashboard.example:443");
    expect((await POST(request("https://DASHBOARD.example", { host: "internal:3000", "x-forwarded-host": "dashboard.example", "x-forwarded-proto": "https" }))).status).toBe(400);
  });
  it("does not let forwarded headers authorize an attacker origin", async () => {
    expect((await POST(request("https://evil.example", { host: "evil.example", "x-forwarded-host": "evil.example", "x-forwarded-proto": "https" }))).status).toBe(403);
    expect(fetch).not.toHaveBeenCalled();
  });
  it.each(["", "null", "http://0.0.0.0:3000", "http://127.0.0.1:3001", "https://127.0.0.1:3000", "http://127.0.0.1:3000.evil.example", "http://127.0.0.1:3000,https://evil.example"])("denies incoming origin %s", async origin => {
    expect((await POST(request(origin))).status).toBe(403);
  });
  it.each(["", "*", "https://*.example", "http://0.0.0.0:3000", "http://dashboard.example", "https://user:pass@example.com", "https://example.com/path", "https://example.com?x=1", "https://example.com#x", "https://example.com\\evil", "https://example.com\n"])("fails closed for invalid configuration %s", async value => {
    vi.stubEnv("DASHBOARD_CANONICAL_ORIGIN", value);
    expect((await POST(request("http://127.0.0.1:3000"))).status).toBe(503); expect(fetch).not.toHaveBeenCalled();
  });
  it("normalizes case and default port while retaining nondefault port", () => {
    expect(normalizeBrowserOrigin("https://EXAMPLE.com:443/")).toBe("https://example.com");
    expect(normalizeBrowserOrigin("https://example.com:8443")).toBe("https://example.com:8443");
  });
  it("does not emit diagnostics in production", async () => {
    vi.stubEnv("DASHBOARD_ORIGIN_DIAGNOSTICS", "1");const logger=vi.spyOn(console,"info");
    await POST(request("http://127.0.0.1:3000"));expect(logger).not.toHaveBeenCalled();logger.mockRestore();
  });
});
