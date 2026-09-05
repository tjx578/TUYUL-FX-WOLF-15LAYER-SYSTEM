// @vitest-environment node
import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { middleware } from "../middleware";

function request(
  path: string,
  options: { cookie?: string; authorization?: string } = {},
): NextRequest {
  const headers = new Headers();
  if (options.authorization) {
    headers.set("authorization", options.authorization);
  }
  const nextRequest = new NextRequest(
    new URL(path, "https://dashboard.example"),
    { headers },
  );
  if (options.cookie) {
    nextRequest.cookies.set("wolf15_session", options.cookie);
  }
  return nextRequest;
}

describe("G4 viewer middleware boundary", () => {
  it.each(["/login", "/healthz", "/api/set-session"])(
    "keeps %s public",
    (path) => {
      expect(middleware(request(path)).status).toBe(200);
    },
  );

  it("redirects an unauthenticated root request to login", () => {
    const response = middleware(request("/"));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      "https://dashboard.example/login",
    );
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it("allows only a JWT-shaped cookie to reach the protected root layout", () => {
    expect(
      middleware(request("/", { cookie: "header.payload.signature" })).status,
    ).toBe(200);
    expect(middleware(request("/", { cookie: "machine-api-key" })).status).toBe(
      307,
    );
  });

  it("denies every non-root page even with a viewer-shaped cookie", async () => {
    const response = middleware(
      request("/trades", { cookie: "header.payload.signature" }),
    );
    expect(response.status).toBe(403);
    await expect(response.json()).resolves.toMatchObject({
      code: "VIEWER_SURFACE_BOUNDARY",
    });
  });

  it("requires a cookie before the proxy route", async () => {
    const response = middleware(request("/api/proxy/dashboard/overview"));
    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toMatchObject({
      code: "SESSION_REQUIRED",
    });
  });

  it("overwrites a caller authorization header with the HttpOnly cookie", () => {
    const response = middleware(
      request("/api/proxy/dashboard/overview", {
        cookie: "header.payload.signature",
        authorization: "Bearer caller-controlled",
      }),
    );
    expect(response.status).toBe(200);
    expect(response.headers.get("x-middleware-request-authorization")).toBe(
      "Bearer header.payload.signature",
    );
  });
});
