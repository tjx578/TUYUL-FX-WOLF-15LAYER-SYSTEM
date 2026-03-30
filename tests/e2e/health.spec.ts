import { test, expect, type APIRequestContext } from "@playwright/test";

/**
 * E2E: Health endpoints — verifies the server is alive and reporting status.
 */

test.describe("Health Endpoints", () => {
  test("GET /health returns liveness payload (P5)", async ({ request }) => {
    const res = await request.get("/health");
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty("status", "alive");
    expect(body).toHaveProperty("service", "tuyul-fx");
  });

  test("GET /api/v1/status/full requires auth (401 without token)", async ({
    request,
  }) => {
    const res = await request.get("/api/v1/status/full");
    expect(res.status()).toBe(401);
  });

  test("GET /api/v1/status/full returns data with valid API key", async ({
    request,
  }) => {
    const res = await request.get("/api/v1/status/full", {
      headers: {
        Authorization: "Bearer e2e-test-api-key-for-playwright",
      },
    });
    // May be 200 (ok) or 200 (degraded) depending on Redis/PG availability
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty("service", "tuyul-fx");
    expect(body).toHaveProperty("version");
  });
});
