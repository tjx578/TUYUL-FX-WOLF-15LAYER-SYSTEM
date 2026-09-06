import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";

import { middleware } from "@/middleware";

const LEGACY_DOMAIN_ROUTES = [
    "/signals",
    "/trades",
    "/risk",
    "/market",
    "/settings",
] as const;

function requestFor(pathname: string): NextRequest {
    const request = new NextRequest(`https://dashboard.example${pathname}`);
    request.cookies.set("wolf15_session", "eyJhbGciOiJIUzI1NiJ9.eyJleHAiOjk5OTk5OTk5OTl9.signature");
    return request;
}

describe("viewer-only domain route boundary", () => {
    it.each(LEGACY_DOMAIN_ROUTES)("denies legacy domain page %s", (pathname) => {
        const response = middleware(requestFor(pathname));

        expect(response.status).toBe(403);
    });
});
