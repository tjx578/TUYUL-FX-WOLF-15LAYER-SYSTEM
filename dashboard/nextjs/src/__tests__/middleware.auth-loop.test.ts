// @vitest-environment node
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

    it("redirects unauthenticated root to /login", () => {
        const res = middleware(makeRequest("/"));
        expect(res.status).toBe(307);
        const loc = new URL(res.headers.get("location")!);
        expect(loc.pathname).toBe("/login");
        expect(loc.searchParams.get("callbackUrl")).toBe("/");
    });

    it("allows authenticated request through", () => {
        const res = middleware(makeRequest("/", { cookie: "valid-session" }));
        expect(res.headers.get("location")).toBeNull();
    });

    it("blocks /audit without admin role", () => {
        const res = middleware(makeRequest("/audit", { cookie: "valid-session" }));
        expect(res.status).toBe(307);
        expect(new URL(res.headers.get("location")!).pathname).toBe("/login");
    });

    it("allows /audit with admin role", () => {
        const res = middleware(
            makeRequest("/audit", { cookie: "valid-session", role: "risk_admin" }),
        );
        expect(res.headers.get("location")).toBeNull();
    });
});