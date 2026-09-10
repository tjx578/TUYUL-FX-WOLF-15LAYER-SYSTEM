// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET, POST } from "@/app/api/proxy/[...path]/route";
import { isAllowlistedReadPath, READ_ONLY_PATHS } from "@/lib/server/readOnlyProxyPolicy";

afterEach(() => vi.restoreAllMocks());

describe("Phase-1 proxy containment", () => {
  it("uses an explicit non-empty read allowlist", () => {
    expect(READ_ONLY_PATHS.length).toBeGreaterThan(0);
    expect(isAllowlistedReadPath("api/v1/accounts/risk-snapshot")).toBe(true);
    expect(isAllowlistedReadPath("dashboard/portfolio")).toBe(true);
  });

  it("rejects execution and near-prefix bypass paths", () => {
    expect(isAllowlistedReadPath("api/v1/execution/order")).toBe(false);
    expect(isAllowlistedReadPath("api/v1/accountsettings")).toBe(false);
    expect(isAllowlistedReadPath("api/v1/config/profile")).toBe(false);
  });

  it("denies mutation methods before contacting any upstream", async () => {
    globalThis.fetch = vi.fn();
    const request = new NextRequest("http://localhost/api/proxy/api/v1/accounts", { method: "POST" });
    const response = await POST(request, { params: Promise.resolve({ path: ["api", "v1", "accounts"] }) });
    expect(response.status).toBe(403);
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("denies an allowlisted GET without a validated session", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response(null, { status: 401 }));
    const request = new NextRequest("http://localhost/api/proxy/api/v1/accounts", {
      headers: { authorization: "Bearer header.payload.signature" },
    });
    const response = await GET(request, { params: Promise.resolve({ path: ["api", "v1", "accounts"] }) });
    expect(response.status).toBe(401);
    expect(globalThis.fetch).toHaveBeenCalledOnce();
  });

  it("does not disclose raw upstream exception details", async () => {
    const secret = "internal-hostname-and-secret";
    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        user_id: "owner", email: "owner@example.test", role: "owner",
      }), { status: 200, headers: { "content-type": "application/json" } }))
      .mockRejectedValueOnce(new Error(secret));
    const request = new NextRequest("http://localhost/api/proxy/api/v1/accounts", {
      headers: { authorization: "Bearer header.payload.signature" },
    });

    const response = await GET(request, {
      params: Promise.resolve({ path: ["api", "v1", "accounts"] }),
    });
    const body = await response.text();

    expect(response.status).toBe(502);
    expect(body).not.toContain(secret);
    expect(body).toContain("UPSTREAM_UNAVAILABLE");
  });
});
