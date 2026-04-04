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
