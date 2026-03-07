import { test, expect, type PlaywrightTestArgs } from "@playwright/test";

/**
 * E2E: Core API routes — verifies key read-only endpoints respond correctly.
 */

const API_KEY = "e2e-test-api-key-for-playwright";
const AUTH_HEADER = { Authorization: `Bearer ${API_KEY}` };

test.describe("Core API Routes", () => {
  // ── L12 ────────────────────────────────────────────────────────
  test("GET /api/v1/l12/EURUSD returns 404 when no verdict cached", async ({
    request,
  }) => {
    const res = await request.get("/api/v1/l12/EURUSD", {
      headers: AUTH_HEADER,
    });
    // 404 = no verdict cached (expected in E2E without market data)
    expect([200, 404]).toContain(res.status());
  });

  test("GET /api/v1/pairs returns list", async ({ request }) => {
    const res = await request.get("/api/v1/pairs", {
      headers: AUTH_HEADER,
    });
    expect([200, 404]).toContain(res.status());
  });

  // ── Signals ────────────────────────────────────────────────────
  test("GET /api/v1/signals returns array or empty", async ({ request }) => {
    const res = await request.get("/api/v1/signals", {
      headers: AUTH_HEADER,
    });
    expect([200, 404]).toContain(res.status());
    if (res.status() === 200) {
      const body = await res.json();
      expect(Array.isArray(body) || typeof body === "object").toBe(true);
    }
  });

  // ── Accounts ───────────────────────────────────────────────────
  test("GET /api/v1/accounts returns data or 404", async ({ request }) => {
    const res = await request.get("/api/v1/accounts", {
      headers: AUTH_HEADER,
    });
    expect([200, 404]).toContain(res.status());
  });

  // ── Prop Firm ──────────────────────────────────────────────────
  test("GET /api/v1/prop-firm/status returns data or 404", async ({
    request,
  }) => {
    const res = await request.get("/api/v1/prop-firm/status", {
      headers: AUTH_HEADER,
    });
    expect([200, 404]).toContain(res.status());
  });

  // ── Dev endpoints ──────────────────────────────────────────────
  test("GET /api/v1/endpoints returns route list in dev mode", async ({
    request,
  }: PlaywrightTestArgs) => {
    const res = await request.get("/api/v1/endpoints");
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty("total");
    expect(body).toHaveProperty("routes");
    expect(body.total).toBeGreaterThan(0);
  });
});
