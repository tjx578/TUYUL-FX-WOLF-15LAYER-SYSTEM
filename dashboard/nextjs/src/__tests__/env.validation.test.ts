/**
 * Regression tests for lib/env.ts fail-fast / degraded-mode behaviour.
 *
 * Tests:
 *  - ConfigError thrown by validateEnv() on deployed hosts with missing WS URL
 *  - validateEnv() does NOT throw on localhost (dev mode)
 *  - getEnvStatus() returns isValid=false with errors when WS URL missing
 *  - getWsBaseUrl() returns "" (not a window.location fallback) on deployed hosts
 *  - getWsBaseUrl() still returns ws://localhost fallback on local dev
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// ── Helpers ───────────────────────────────────────────────────

function setEnv(env: Record<string, string | undefined>) {
    const mergedEnv: Record<string, string | undefined> = {
        ...process.env,
        ...env,
    };
    process.env = Object.fromEntries(
        Object.entries(mergedEnv).filter(([, v]) => v !== undefined),
    ) as NodeJS.ProcessEnv;
}

function mockWindow(hostname: string, protocol = "https:") {
    Object.defineProperty(globalThis, "window", {
        value: {
            location: {
                hostname,
                host: `${hostname}:3000`,
                protocol,
            },
        },
        writable: true,
        configurable: true,
    });
}

function restoreWindow(original: typeof globalThis.window | undefined) {
    Object.defineProperty(globalThis, "window", {
        value: original,
        writable: true,
        configurable: true,
    });
}

beforeEach(() => {
    setEnv({
        NEXT_PUBLIC_WS_BASE_URL: undefined,
        NEXT_PUBLIC_API_BASE_URL: undefined,
        NEXT_PUBLIC_WS_URL: undefined,
        NEXT_PUBLIC_API_URL: undefined,
    });
});

afterEach(() => {
    vi.restoreAllMocks();
});

// ══════════════════════════════════════════════════════════════
//  ConfigError fail-fast on deployed host
// ══════════════════════════════════════════════════════════════

describe("validateEnv — deployed host (fail-fast)", () => {
    it("throws ConfigError with ENV_WS_URL_MISSING code when WS URL not set on Vercel host", async () => {
        const originalWindow = globalThis.window;
        mockWindow("my-app.vercel.app", "https:");

        const mod = await import("@/lib/env");
        expect(() => mod.validateEnv()).toThrow("NEXT_PUBLIC_WS_BASE_URL");

        try {
            mod.validateEnv();
        } catch (err) {
            expect(err).toBeInstanceOf(mod.ConfigError);
            if (err instanceof mod.ConfigError) {
                expect(err.code).toBe("ENV_WS_URL_MISSING");
                expect(err.missingVars).toContain("NEXT_PUBLIC_WS_BASE_URL");
            }
        }

        restoreWindow(originalWindow);
    });

    it("throws ConfigError on railway.app host with missing WS URL", async () => {
        const originalWindow = globalThis.window;
        mockWindow("my-service.railway.app", "https:");

        const mod = await import("@/lib/env");
        expect(() => mod.validateEnv()).toThrow(mod.ConfigError);

        restoreWindow(originalWindow);
    });

    it("does NOT throw when NEXT_PUBLIC_WS_BASE_URL is set on deployed host", async () => {
        process.env.NEXT_PUBLIC_WS_BASE_URL = "wss://api.up.railway.app";
        const originalWindow = globalThis.window;
        mockWindow("my-app.vercel.app", "https:");

        const mod = await import("@/lib/env");
        expect(() => mod.validateEnv()).not.toThrow();

        restoreWindow(originalWindow);
    });
});

// ══════════════════════════════════════════════════════════════
//  validateEnv — local dev (no throw)
// ══════════════════════════════════════════════════════════════

describe("validateEnv — local dev (no throw)", () => {
    it("does NOT throw on localhost even when WS URL is missing", async () => {
        const originalWindow = globalThis.window;
        mockWindow("localhost", "http:");

        const mod = await import("@/lib/env");
        expect(() => mod.validateEnv()).not.toThrow();

        restoreWindow(originalWindow);
    });

    it("does NOT throw on 127.0.0.1 when WS URL is missing", async () => {
        const originalWindow = globalThis.window;
        mockWindow("127.0.0.1", "http:");

        const mod = await import("@/lib/env");
        expect(() => mod.validateEnv()).not.toThrow();

        restoreWindow(originalWindow);
    });
});

// ══════════════════════════════════════════════════════════════
//  getEnvStatus — degraded mode detection
// ══════════════════════════════════════════════════════════════

describe("getEnvStatus", () => {
    it("returns isValid=false and non-empty errors when WS URL is missing", async () => {
        const mod = await import("@/lib/env");
        const status = mod.getEnvStatus();
        expect(status.isValid).toBe(false);
        expect(status.errors.length).toBeGreaterThan(0);
        expect(status.errors[0]).toContain("NEXT_PUBLIC_WS_BASE_URL");
    });

    it("returns isValid=true when WS URL is configured", async () => {
        process.env.NEXT_PUBLIC_WS_BASE_URL = "wss://api.up.railway.app";
        const mod = await import("@/lib/env");
        const status = mod.getEnvStatus();
        expect(status.isValid).toBe(true);
        expect(status.errors).toHaveLength(0);
        expect(status.wsUrl).toBe("wss://api.up.railway.app");
    });

    it("returns the resolved wsUrl from the status object", async () => {
        process.env.NEXT_PUBLIC_WS_BASE_URL = "wss://backend.railway.app/";
        const mod = await import("@/lib/env");
        const status = mod.getEnvStatus();
        expect(status.wsUrl).toBe("wss://backend.railway.app");
    });
});

// ══════════════════════════════════════════════════════════════
//  getWsBaseUrl — no window.location fallback on deployed hosts
// ══════════════════════════════════════════════════════════════

describe("getWsBaseUrl — deployed host hard-fail", () => {
    it("returns empty string (not window.location) on vercel.app host when env var missing", async () => {
        const originalWindow = globalThis.window;
        mockWindow("my-app.vercel.app", "https:");

        const mod = await import("@/lib/env");
        expect(mod.getWsBaseUrl()).toBe("");

        restoreWindow(originalWindow);
    });

    it("returns empty string on non-localhost host when env var missing", async () => {
        const originalWindow = globalThis.window;
        mockWindow("my-api.up.railway.app", "https:");

        const mod = await import("@/lib/env");
        expect(mod.getWsBaseUrl()).toBe("");

        restoreWindow(originalWindow);
    });

    it("still returns ws:// from localhost when env var missing (local dev allowed)", async () => {
        const originalWindow = globalThis.window;
        mockWindow("localhost", "http:");

        const mod = await import("@/lib/env");
        expect(mod.getWsBaseUrl()).toBe("ws://localhost:3000");

        restoreWindow(originalWindow);
    });
});
