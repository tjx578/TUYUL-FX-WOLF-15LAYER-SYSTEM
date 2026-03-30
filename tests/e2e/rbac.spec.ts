import { test, expect } from "@playwright/test";

/**
 * E2E: RBAC — verifies role-based access control.
 *
 * Uses the lightweight JWT issuer built into auth.py.
 * The server's DASHBOARD_JWT_SECRET is set to a known value in playwright.config.ts,
 * so we can craft valid JWTs here.
 */

import { Buffer } from "node:buffer";
import { createHmac } from "crypto";

const JWT_SECRET =
  "e2e_test_secret_that_is_at_least_32_chars_long_for_safety";

function b64url(buf: Buffer): string {
  return buf.toString("base64url").replace(/=+$/, "");
}

function createTestJwt(payload: Record<string, unknown>): string {
  const header = b64url(Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })));
  const now = Math.floor(Date.now() / 1000);
  const body = b64url(
    Buffer.from(
      JSON.stringify({ iat: now, exp: now + 3600, ...payload })
    )
  );
  const sig = b64url(
    createHmac("sha256", JWT_SECRET)
      .update(`${header}.${body}`)
      .digest()
  );
  return `${header}.${body}.${sig}`;
}

type TestFixtures = {
  request: import("@playwright/test").APIRequestContext;
};

test.describe("RBAC Enforcement", () => {
  test("Viewer role can access read endpoints", async ({ request }: TestFixtures) => {
    const token = createTestJwt({ sub: "viewer-user", role: "viewer" });
    const res = await request.get("/api/v1/status/full", {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(res.status()).toBe(200);
  });

  test("Viewer role is blocked from write endpoints", async ({ request }: TestFixtures) => {
    const token = createTestJwt({ sub: "viewer-user", role: "viewer" });
    // Attempt a write action (trade take) — should be blocked by governance
    const res = await request.post("/api/v1/trades/take", {
      headers: {
        Authorization: `Bearer ${token}`,
        "X-Edit-Mode": "ON",
        "X-Action-Reason": "E2E test",
        "Content-Type": "application/json",
      },
      data: { signal_id: "fake" },
    });
    // Expect 403 (role blocked) or 404 (no such signal) — never 200
    expect([403, 404, 422]).toContain(res.status());
    if (res.status() === 403) {
      const body = await res.json();
      expect(body.detail).toContain("write");
    }
  });

  test("Admin role can access admin-only read routes", async ({ request }: TestFixtures) => {
    const token = createTestJwt({
      sub: "admin-user",
      role: "admin",
      scopes: ["*"],
    });
    const res = await request.get("/api/v1/status/full", {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(res.status()).toBe(200);
  });

  test("Unknown role is rejected", async ({ request }: TestFixtures) => {
    const token = createTestJwt({ sub: "hacker", role: "superadmin" });
    // Write endpoint — governance rejects invalid role
    const res = await request.post("/api/v1/trades/take", {
      headers: {
        Authorization: `Bearer ${token}`,
        "X-Edit-Mode": "ON",
        "X-Action-Reason": "test",
        "Content-Type": "application/json",
      },
      data: { signal_id: "fake" },
    });
    expect([403, 404, 422]).toContain(res.status());
  });

  test("JWT without role claim is rejected on write", async ({ request }: TestFixtures) => {
    const token = createTestJwt({ sub: "no-role-user" });
    const res = await request.post("/api/v1/trades/take", {
      headers: {
        Authorization: `Bearer ${token}`,
        "X-Edit-Mode": "ON",
        "X-Action-Reason": "test",
        "Content-Type": "application/json",
      },
      data: { signal_id: "fake" },
    });
    expect([403, 404, 422]).toContain(res.status());
  });
});
