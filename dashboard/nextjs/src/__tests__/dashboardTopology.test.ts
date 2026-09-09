import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getCoreApiUrl, resolveDashboardUpstream } from "@/lib/server/dashboardTopology";
import { VIEWER_PROXY_PATHS } from "@/lib/viewerContract";

beforeEach(() => { vi.stubEnv("INTERNAL_API_URL", "https://core.example/"); });
afterEach(() => { vi.unstubAllEnvs(); });

describe("Railway direct core topology", () => {
  it("normalizes the server-only core origin", () => { expect(getCoreApiUrl()).toBe("https://core.example"); });
  it.each(VIEWER_PROXY_PATHS)("routes only %s to core", path => {
    expect(resolveDashboardUpstream(path)).toEqual({url:"https://core.example",surface:"core-api"});
  });
  it.each(["dashboard/overview/extra", "dashboard/settings", "api/v1/status", "api/v1/execution/order", "bff/aggregated-status"])("rejects %s instead of granting fallback access", path => {
    expect(resolveDashboardUpstream(path)).toBeNull();
  });
  it.each(["", " https://core.example", "https://user:password@core.example", "https://core.example/api", "https://core.example?x=1", "https://core.example#x", "https://core.example/%2e", "https://*.example", "http://core.example", "https://0.0.0.0"])("fails closed for invalid origin %s", value => {
    vi.stubEnv("INTERNAL_API_URL",value); expect(getCoreApiUrl()).toBeNull();
  });
  it("does not fall back to public or legacy configuration", () => {
    vi.stubEnv("INTERNAL_API_URL", ""); vi.stubEnv("NEXT_PUBLIC_API_BASE_URL","https://public.example");
    expect(getCoreApiUrl()).toBeNull();
  });
  it("requires HTTPS in production including loopback", () => {
    vi.stubEnv("NODE_ENV","production"); vi.stubEnv("INTERNAL_API_URL","http://localhost:8000");
    expect(getCoreApiUrl()).toBeNull();
  });
  it("allows HTTP loopback only in local development", () => {
    vi.stubEnv("NODE_ENV","test"); vi.stubEnv("INTERNAL_API_URL","http://localhost:8000");
    expect(getCoreApiUrl()).toBe("http://localhost:8000");
  });
  it("rejects the frontend canonical origin as the backend", () => {
    vi.stubEnv("DASHBOARD_CANONICAL_ORIGIN","https://core.example"); expect(getCoreApiUrl()).toBeNull();
  });
});
