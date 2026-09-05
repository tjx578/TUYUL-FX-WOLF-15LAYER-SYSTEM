// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import {
  DELETE,
  GET,
  PATCH,
  POST,
  PUT,
} from "@/app/api/proxy/[...path]/route";
import {
  isAllowlistedReadPath,
  READ_ONLY_PATHS,
} from "@/lib/server/readOnlyProxyPolicy";

const viewerSession = {
  user_id: "viewer-1",
  email: "viewer@example.test",
  role: "viewer",
  scopes: ["read:dashboard"],
  auth_method: "jwt",
};

function request(path: string, method = "GET"): NextRequest {
  return new NextRequest("https://dashboard.example/api/proxy/" + path, {
    method,
    headers: {
      authorization: "Bearer header.payload.signature",
      cookie: "wolf15_session=must-not-forward",
    },
  });
}

function context(path: string) {
  return { params: Promise.resolve({ path: path.split("/") }) };
}

beforeEach(() => {
  process.env.INTERNAL_API_URL = "https://core.example";
  process.env.INTERNAL_DASHBOARD_BFF_URL = "https://bff.example";
});

afterEach(() => {
  delete process.env.INTERNAL_API_URL;
  delete process.env.INTERNAL_DASHBOARD_BFF_URL;
  vi.restoreAllMocks();
});

describe("G4 viewer proxy containment", () => {
  it("has exactly three GET paths and rejects prefix/traversal variants", () => {
    expect(READ_ONLY_PATHS).toEqual([
      "dashboard/overview",
      "dashboard/feed-status",
      "bff/aggregated-status",
    ]);

    for (const path of READ_ONLY_PATHS) {
      expect(isAllowlistedReadPath(path)).toBe(true);
    }

    for (const path of [
      "dashboard",
      "dashboard/overview/extra",
      "dashboard/settings",
      "bff",
      "bff/aggregated-status/extra",
      "api/v1/status",
      "api/v1/execution/order",
      "dashboard/%2e%2e/settings",
      "dashboard/../settings",
      "/dashboard/overview",
      "dashboard/overview/",
    ]) {
      expect(isAllowlistedReadPath(path)).toBe(false);
    }
  });

  it.each([
    ["POST", POST],
    ["PUT", PUT],
    ["PATCH", PATCH],
    ["DELETE", DELETE],
  ])("denies %s before auth or upstream", async (method, handler) => {
    globalThis.fetch = vi.fn();
    const response = await handler(
      request("dashboard/overview", method),
      context("dashboard/overview"),
    );
    expect(response.status).toBe(403);
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("rejects a non-viewer core session before the BFF call", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          user_id: "owner",
          email: "owner@example.test",
          role: "owner",
          scopes: ["read:dashboard"],
          auth_method: "jwt",
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    const response = await GET(
      request("dashboard/overview"),
      context("dashboard/overview"),
    );
    expect(response.status).toBe(401);
    expect(globalThis.fetch).toHaveBeenCalledOnce();
  });

  it("forwards an authorized GET only to the configured BFF", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(viewerSession), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "ok", source: "real-bff" }), {
          status: 200,
          headers: {
            "content-type": "application/json",
            "x-bff-cache": "MISS",
          },
        }),
      );

    const response = await GET(
      request("dashboard/overview"),
      context("dashboard/overview"),
    );

    expect(response.status).toBe(200);
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
    expect(vi.mocked(globalThis.fetch).mock.calls[1]?.[0]).toBe(
      "https://bff.example/api/dashboard/overview",
    );

    const init = vi.mocked(globalThis.fetch).mock.calls[1]?.[1];
    const headers = init?.headers as Headers;
    expect(headers.get("authorization")).toBe(
      "Bearer header.payload.signature",
    );
    expect(headers.get("cookie")).toBeNull();
    expect(response.headers.get("x-proxy-surface")).toBe("bff");
    expect(response.headers.get("x-bff-cache")).toBe("MISS");
  });

  it("fails closed when the BFF URL is missing", async () => {
    delete process.env.INTERNAL_DASHBOARD_BFF_URL;
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(viewerSession), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const response = await GET(
      request("bff/aggregated-status"),
      context("bff/aggregated-status"),
    );

    expect(response.status).toBe(503);
    expect(globalThis.fetch).toHaveBeenCalledOnce();
  });

  it("sanitizes BFF connection errors", async () => {
    const secret = "private-host-and-secret";
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(viewerSession), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      )
      .mockRejectedValueOnce(new Error(secret));

    const response = await GET(
      request("dashboard/feed-status"),
      context("dashboard/feed-status"),
    );
    const body = await response.text();

    expect(response.status).toBe(502);
    expect(body).toContain("UPSTREAM_UNAVAILABLE");
    expect(body).not.toContain(secret);
  });
});
