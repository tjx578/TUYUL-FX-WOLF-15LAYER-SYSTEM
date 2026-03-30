import { test, expect } from "@playwright/test";

/**
 * E2E: Authentication & Authorization — verifies JWT/API-key flows.
 */

const API_KEY = "e2e-test-api-key-for-playwright";

test.describe("Authentication", () => {
  test("Unauthenticated request to protected route returns 401", async ({
    request,
  }) => {
    const res = await request.get("/api/v1/status/full");
    expect(res.status()).toBe(401);
  });

  test("Invalid Bearer token returns 401", async ({ request }) => {
    const res = await request.get("/api/v1/status/full", {
      headers: { Authorization: "Bearer totally-invalid-token" },
    });
    expect(res.status()).toBe(401);
  });

  test("Valid API key grants access", async ({ request }) => {
    const res = await request.get("/api/v1/status/full", {
      headers: { Authorization: `Bearer ${API_KEY}` },
    });
    expect(res.status()).toBe(200);
  });

  test("Malformed Authorization scheme is rejected", async ({ request }) => {
    const res = await request.get("/api/v1/status/full", {
      headers: { Authorization: `Basic ${API_KEY}` },
    });
    expect(res.status()).toBe(401);
  });
});
