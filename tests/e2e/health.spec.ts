import { test, expect, type APIRequestContext } from "@playwright/test";

/**
 * E2E: Health endpoints — verifies the server is alive and reporting status.
 */

test.describe("Health Endpoints", () => {
  test("GET /health returns 200 with status ok", async ({ request }) => {
    const res = await request.get("/health");
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty("status", "ok");
  });

  test("GET /health/full requires auth (401 without token)", async ({
    request,
  }) => {
    const res = await request.get("/health/full");
    expect(res.status()).toBe(401);
  });

  test("GET /health/full returns data with valid API key", async ({
    request,
  }) => {
    const res = await request.get("/health/full", {
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
