// @vitest-environment node
import { describe, it, expect } from "vitest";
import { NextRequest, NextResponse } from "next/server";
import { middleware } from "../middleware";

function makeRequest(
    path: string,
    opts: { cookie?: string; role?: string } = {},
): NextRequest {
    const url = new URL(path, "http://localhost:3000");
    const req = new NextRequest(url);
    if (opts.cookie) {
        req.cookies.set("wolf15_session", opts.cookie);
    }
    if (opts.role) {
        req.headers.set("x-user-role", opts.role);
    }
    return req;
}

describe("middleware auth-loop prevention", () => {
    it("allows /login through without redirect (no cookie)", () => {
        const res = middleware(makeRequest("/login"));
        expect(res.headers.get("location")).toBeNull();
    });

    it("allows /login subpath through without redirect", () => {
        const res = middleware(makeRequest("/login/callback"));
        expect(res.headers.get("location")).toBeNull();
    });

    it("allows unauthenticated root through (owner mode — no redirect)", () => {
        const res = middleware(makeRequest("/"));
        // handlePageRoute returns NextResponse.next() unconditionally in owner mode.
        // The server-side auth (serverAuth.ts) returns the owner user without a session.
        expect(res.headers.get("location")).toBeNull();
    });

    it("allows authenticated request through", () => {
        const res = middleware(makeRequest("/", { cookie: "valid-session" }));
        expect(res.headers.get("location")).toBeNull();
    });

    it("allows /audit without admin role through (owner mode — no redirect)", () => {
        // handlePageRoute is disabled in owner mode — all page routes pass through.
        const res = middleware(makeRequest("/audit", { cookie: "valid-session" }));
        expect(res.headers.get("location")).toBeNull();
    });

    it("allows /audit with admin role", () => {
        const res = middleware(
            makeRequest("/audit", { cookie: "valid-session", role: "risk_admin" }),
        );
        expect(res.headers.get("location")).toBeNull();
    });
});