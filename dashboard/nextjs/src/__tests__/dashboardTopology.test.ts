import { describe, it, expect, beforeEach, afterEach } from "vitest";
import {
    getCoreApiUrl,
    resolveDashboardUpstream,
    resolveOperatorStatusSurface,
    BFF_ALLOWLISTED_PATHS,
} from "@/lib/server/dashboardTopology";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const ENV_BACKUP: Record<string, string | undefined> = {};

function setEnv(vars: Record<string, string | undefined>) {
    for (const [key, value] of Object.entries(vars)) {
        if (!(key in ENV_BACKUP)) ENV_BACKUP[key] = process.env[key];
        if (value === undefined) {
            delete process.env[key];
        } else {
            process.env[key] = value;
        }
    }
}

function restoreEnv() {
    for (const [key, value] of Object.entries(ENV_BACKUP)) {
        if (value === undefined) {
            delete process.env[key];
        } else {
            process.env[key] = value;
        }
    }
    // clear backup for next test
    for (const key of Object.keys(ENV_BACKUP)) delete ENV_BACKUP[key];
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("getCoreApiUrl", () => {
    beforeEach(() => {
        setEnv({
            INTERNAL_API_URL: undefined,
            NEXT_PUBLIC_API_BASE_URL: undefined,
            NODE_ENV: "test",
        });
    });

    afterEach(restoreEnv);

    it("returns INTERNAL_API_URL when set", () => {
        setEnv({ INTERNAL_API_URL: "https://core.railway.internal" });
        expect(getCoreApiUrl()).toBe("https://core.railway.internal");
    });

    it("falls back to NEXT_PUBLIC_API_BASE_URL", () => {
        setEnv({ NEXT_PUBLIC_API_BASE_URL: "https://core.up.railway.app" });
        expect(getCoreApiUrl()).toBe("https://core.up.railway.app");
    });

    it("strips trailing slashes", () => {
        setEnv({ INTERNAL_API_URL: "https://core.railway.internal///" });
        expect(getCoreApiUrl()).toBe("https://core.railway.internal");
    });

    it("returns localhost fallback in non-production", () => {
        setEnv({ NODE_ENV: "development" });
        expect(getCoreApiUrl()).toBe("http://localhost:8000");
    });

    it("returns null in production when no env is set", () => {
        setEnv({ NODE_ENV: "production" });
        expect(getCoreApiUrl()).toBeNull();
    });
});

describe("BFF_ALLOWLISTED_PATHS", () => {
    it("contains expected prefixes", () => {
        expect(BFF_ALLOWLISTED_PATHS).toContain("dashboard/");
        expect(BFF_ALLOWLISTED_PATHS).toContain("bff/");
    });

    it("is frozen / readonly at runtime", () => {
        expect(Object.isFrozen(BFF_ALLOWLISTED_PATHS)).toBe(true);
    });
});

describe("resolveDashboardUpstream", () => {
    beforeEach(() => {
        setEnv({
            INTERNAL_API_URL: "https://core.railway.internal",
            INTERNAL_DASHBOARD_BFF_URL: undefined,
            NODE_ENV: "test",
        });
    });

    afterEach(restoreEnv);

    it("routes to core-api when BFF URL is not set", () => {
        const result = resolveDashboardUpstream("dashboard/portfolio");
        expect(result).toEqual({
            url: "https://core.railway.internal",
            surface: "core-api",
        });
    });

    it("routes allowlisted path to BFF when BFF URL is set", () => {
        setEnv({ INTERNAL_DASHBOARD_BFF_URL: "https://bff.railway.internal" });
        const result = resolveDashboardUpstream("dashboard/portfolio");
        expect(result).toEqual({
            url: "https://bff.railway.internal",
            surface: "bff",
        });
    });

    it("routes bff/ prefix to BFF", () => {
        setEnv({ INTERNAL_DASHBOARD_BFF_URL: "https://bff.railway.internal" });
        const result = resolveDashboardUpstream("bff/aggregated-status");
        expect(result).toEqual({
            url: "https://bff.railway.internal",
            surface: "bff",
        });
    });

    it("routes non-allowlisted path to core-api even when BFF is set", () => {
        setEnv({ INTERNAL_DASHBOARD_BFF_URL: "https://bff.railway.internal" });
        const result = resolveDashboardUpstream("v1/status");
        expect(result).toEqual({
            url: "https://core.railway.internal",
            surface: "core-api",
        });
    });

    it("strips trailing slash from BFF URL", () => {
        setEnv({ INTERNAL_DASHBOARD_BFF_URL: "https://bff.railway.internal/" });
        const result = resolveDashboardUpstream("dashboard/portfolio");
        expect(result!.url).toBe("https://bff.railway.internal");
    });

    it("returns null when core-api is unconfigured in production", () => {
        setEnv({
            NODE_ENV: "production",
            INTERNAL_API_URL: undefined,
            NEXT_PUBLIC_API_BASE_URL: undefined,
        });
        const result = resolveDashboardUpstream("v1/health");
        expect(result).toBeNull();
    });

    it("returns BFF even when core-api is unconfigured (BFF path)", () => {
        setEnv({
            NODE_ENV: "production",
            INTERNAL_API_URL: undefined,
            NEXT_PUBLIC_API_BASE_URL: undefined,
            INTERNAL_DASHBOARD_BFF_URL: "https://bff.railway.internal",
        });
        const result = resolveDashboardUpstream("dashboard/portfolio");
        expect(result).toEqual({
            url: "https://bff.railway.internal",
            surface: "bff",
        });
    });
});

describe("resolveOperatorStatusSurface", () => {
    beforeEach(() => {
        setEnv({
            INTERNAL_API_URL: "https://core.railway.internal",
            NODE_ENV: "test",
        });
    });

    afterEach(restoreEnv);

    it("always routes to core-api", () => {
        const result = resolveOperatorStatusSurface();
        expect(result).toEqual({
            url: "https://core.railway.internal",
            surface: "core-api",
        });
    });

    it("returns null when core-api unconfigured in production", () => {
        setEnv({
            NODE_ENV: "production",
            INTERNAL_API_URL: undefined,
            NEXT_PUBLIC_API_BASE_URL: undefined,
        });
        expect(resolveOperatorStatusSurface()).toBeNull();
    });
});

// ---------------------------------------------------------------------------
// Mutation path behavior — BFF routes must forward all HTTP methods
// ---------------------------------------------------------------------------

describe("resolveDashboardUpstream — mutation paths", () => {
    beforeEach(() => {
        setEnv({
            INTERNAL_API_URL: "https://core.railway.internal",
            INTERNAL_DASHBOARD_BFF_URL: "https://bff.railway.internal",
            NODE_ENV: "test",
        });
    });

    afterEach(restoreEnv);

    it("routes POST-eligible dashboard/ path to BFF (resolver is method-agnostic)", () => {
        // The resolver is path-only; HTTP method filtering is the proxy's job.
        // Verify the resolver routes regardless of what the caller intends.
        const result = resolveDashboardUpstream("dashboard/settings");
        expect(result).toEqual({
            url: "https://bff.railway.internal",
            surface: "bff",
        });
    });

    it("routes mutation-capable core path to core-api, not BFF", () => {
        const result = resolveDashboardUpstream("api/v1/trades/active");
        expect(result).toEqual({
            url: "https://core.railway.internal",
            surface: "core-api",
        });
    });

    it("never routes constitutional paths to BFF", () => {
        const constitutionalPaths = [
            "api/v1/verdict",
            "api/v1/execution/order",
            "api/v1/risk/firewall",
            "api/v1/governance/mode",
        ];
        for (const path of constitutionalPaths) {
            const result = resolveDashboardUpstream(path);
            expect(result?.surface).toBe("core-api");
        }
    });
});

// ---------------------------------------------------------------------------
// Observability surface header contract
// ---------------------------------------------------------------------------

describe("resolveDashboardUpstream — surface header values", () => {
    beforeEach(() => {
        setEnv({
            INTERNAL_API_URL: "https://core.railway.internal",
            INTERNAL_DASHBOARD_BFF_URL: "https://bff.railway.internal",
            NODE_ENV: "test",
        });
    });

    afterEach(restoreEnv);

    it('returns surface "bff" for allowlisted path', () => {
        const result = resolveDashboardUpstream("dashboard/portfolio");
        expect(result!.surface).toBe("bff");
    });

    it('returns surface "core-api" for non-allowlisted path', () => {
        const result = resolveDashboardUpstream("api/v1/status");
        expect(result!.surface).toBe("core-api");
    });

    it('returns surface "core-api" when BFF not configured', () => {
        setEnv({ INTERNAL_DASHBOARD_BFF_URL: undefined });
        const result = resolveDashboardUpstream("dashboard/portfolio");
        expect(result!.surface).toBe("core-api");
    });

    it("resolveOperatorStatusSurface always returns core-api surface", () => {
        const result = resolveOperatorStatusSurface();
        expect(result!.surface).toBe("core-api");
    });
});

// ---------------------------------------------------------------------------
// BFF-unreachable scenario — resolver still resolves; error is at fetch time
// ---------------------------------------------------------------------------

describe("resolveDashboardUpstream — BFF URL configured but service down", () => {
    beforeEach(() => {
        setEnv({
            INTERNAL_API_URL: "https://core.railway.internal",
            INTERNAL_DASHBOARD_BFF_URL: "https://bff-down.railway.internal",
            NODE_ENV: "test",
        });
    });

    afterEach(restoreEnv);

    it("still resolves to BFF URL (no silent fallback to core-api)", () => {
        // The resolver MUST return the BFF URL even if the service is down.
        // Fallback to core-api is explicitly forbidden (phantom routing drift).
        // The proxy layer is responsible for returning a 502, not the resolver.
        const result = resolveDashboardUpstream("dashboard/portfolio");
        expect(result).toEqual({
            url: "https://bff-down.railway.internal",
            surface: "bff",
        });
    });

    it("does NOT fall back to core-api for BFF-allowlisted paths", () => {
        const result = resolveDashboardUpstream("bff/aggregated-status");
        expect(result!.url).not.toBe("https://core.railway.internal");
        expect(result!.surface).toBe("bff");
    });

    it("still routes non-allowlisted paths to core-api", () => {
        const result = resolveDashboardUpstream("api/v1/status");
        expect(result).toEqual({
            url: "https://core.railway.internal",
            surface: "core-api",
        });
    });
});
