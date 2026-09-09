// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const validateSessionToken = vi.hoisted(() => vi.fn());
vi.mock("@/lib/serverAuth", () => ({ validateSessionToken }));

import { DELETE, POST } from "@/app/api/set-session/route";

let ipSequence = 0;

function token(options: { alg?: string; exp?: number } = {}): string {
  const header = Buffer.from(
    JSON.stringify({ alg: options.alg ?? "HS256", typ: "JWT" }),
  ).toString("base64url");
  const payload = Buffer.from(
    JSON.stringify({
      sub: "viewer-1",
      exp: options.exp ?? Math.floor(Date.now() / 1000) + 3600,
    }),
  ).toString("base64url");
  return header + "." + payload + ".validsignaturesegment";
}

function request(rawToken: string): NextRequest {
  ipSequence += 1;
  return new NextRequest("https://dashboard.example/api/set-session", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-forwarded-for": "192.0.2." + ipSequence,
    },
    body: JSON.stringify({ token: rawToken }),
  });
}

afterEach(() => {
  validateSessionToken.mockReset();
});

describe("viewer session establishment", () => {
  it("sets an HttpOnly cookie only after strict viewer validation", async () => {
    validateSessionToken.mockResolvedValue({
      user_id: "viewer-1",
      email: "viewer@example.test",
      role: "viewer",
      scopes: ["read:dashboard"],
      auth_method: "jwt",
    });

    const rawToken = token();
    const response = await POST(request(rawToken));
    const body = await response.text();

    expect(response.status).toBe(200);
    expect(body).not.toContain(rawToken);
    expect(response.headers.get("set-cookie")).toContain("wolf15_session=");
    expect(response.headers.get("set-cookie")?.toLowerCase()).toContain(
      "httponly",
    );
    expect(validateSessionToken).toHaveBeenCalledWith(rawToken);
  });

  it("rejects a cryptographically valid but unauthorized session", async () => {
    validateSessionToken.mockResolvedValue(null);
    const response = await POST(request(token()));

    expect(response.status).toBe(403);
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it("rejects expired and non-HS256 tokens before core validation", async () => {
    const expired = await POST(
      request(token({ exp: Math.floor(Date.now() / 1000) - 1 })),
    );
    const wrongAlgorithm = await POST(request(token({ alg: "none" })));

    expect(expired.status).toBe(400);
    expect(wrongAlgorithm.status).toBe(400);
    expect(validateSessionToken).not.toHaveBeenCalled();
  });

  it("clears the browser session without contacting an upstream", async () => {
    const response = await DELETE();
    expect(response.status).toBe(200);
    expect(response.headers.get("set-cookie")).toContain("wolf15_session=");
    expect(validateSessionToken).not.toHaveBeenCalled();
  });
});
