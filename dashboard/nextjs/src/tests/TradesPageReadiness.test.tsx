import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";

import { middleware } from "@/middleware";

describe("TradeDesk viewer boundary", () => {
  it("keeps the execution-oriented trade desk unavailable to a viewer session", () => {
    const request = new NextRequest("https://dashboard.example/trades");
    request.cookies.set(
      "wolf15_session",
      "eyJhbGciOiJIUzI1NiJ9.eyJleHAiOjk5OTk5OTk5OTl9.signature",
    );

    expect(middleware(request).status).toBe(403);
  });
});
