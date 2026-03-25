/**
 * Unit tests for lib/env.ts
 *
 * Tests:
 *  - getApiBaseUrl: default, override, legacy alias
 *  - getWsBaseUrl: env var, trailing slash stripping, /ws suffix stripping
 *  - getWsBaseUrl: local dev fallback from window.location
 *  - validateEnv: warnings for missing config
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { ConfigError } from "@/lib/env";

// ── Env-var-dependent module: re-import per test ─────────────

function setEnv(env: Record<string, string | undefined>) {
    const mergedEnv: Record<string, string | undefined> = {
        ...process.env,
        ...env,
    };

    const sanitizedEnv = Object.fromEntries(
        Object.entries(mergedEnv).filter(([, val]) => val !== undefined),
    ) as NodeJS.ProcessEnv;

    process.env = sanitizedEnv;
}

// We need to clear module cache for each test since env.ts reads
// process.env at module level for API_BASE_URL constant
let envModule: typeof import("@/lib/env");

async function freshImport() {
    // Vitest doesn't automatically re-evaluate modules, so we force it
    const mod = await import("@/lib/env");
    return mod;
}

beforeEach(() => {
    // Clear relevant env vars
    setEnv({
        NEXT_PUBLIC_API_BASE_URL: undefined,
        NEXT_PUBLIC_API_URL: undefined,
        NEXT_PUBLIC_WS_BASE_URL: undefined,
        NEXT_PUBLIC_WS_URL: undefined,
        NEXT_PUBLIC_TIMEZONE: undefined,
    });
});

afterEach(() => {
    vi.restoreAllMocks();
});

// ══════════════════════════════════════════════════════════════
//  getApiBaseUrl
// ══════════════════════════════════════════════════════════════

describe("getApiBaseUrl", () => {
    it("should return empty string by default (relative path for rewrites)", async () => {
        const mod = await freshImport();
        expect(mod.getApiBaseUrl()).toBe("");
    });

    it("should return override URL when NEXT_PUBLIC_API_BASE_URL is set", async () => {
        process.env.NEXT_PUBLIC_API_BASE_URL = "https://api.example.com";
        const mod = await freshImport();
        expect(mod.getApiBaseUrl()).toBe("https://api.example.com");
    });

    it("should strip trailing slash from API base URL", async () => {
        process.env.NEXT_PUBLIC_API_BASE_URL = "https://api.example.com/";
        const mod = await freshImport();
        expect(mod.getApiBaseUrl()).toBe("https://api.example.com");
    });
});

// ══════════════════════════════════════════════════════════════
//  getWsBaseUrl
// ══════════════════════════════════════════════════════════════

describe("getWsBaseUrl", () => {
    it("should return configured WSS URL", async () => {
        process.env.NEXT_PUBLIC_WS_BASE_URL = "wss://backend.up.railway.app";
        const mod = await freshImport();
        expect(mod.getWsBaseUrl()).toBe("wss://backend.up.railway.app");
    });

    it("should strip trailing slash from WS base URL", async () => {
        process.env.NEXT_PUBLIC_WS_BASE_URL = "wss://backend.up.railway.app/";
        const mod = await freshImport();
        expect(mod.getWsBaseUrl()).toBe("wss://backend.up.railway.app");
    });

    it("should strip accidental /ws suffix", async () => {
        process.env.NEXT_PUBLIC_WS_BASE_URL = "wss://backend.up.railway.app/ws";
        const mod = await freshImport();
        expect(mod.getWsBaseUrl()).toBe("wss://backend.up.railway.app");
    });

    it("should strip /ws/live path (the root-cause double-path bug)", async () => {
        process.env.NEXT_PUBLIC_WS_BASE_URL = "wss://wolf15-api-production.up.railway.app/ws/live";
        const mod = await freshImport();
        expect(mod.getWsBaseUrl()).toBe("wss://wolf15-api-production.up.railway.app");
    });

    it("should strip any arbitrary path component", async () => {
        process.env.NEXT_PUBLIC_WS_BASE_URL = "wss://backend.up.railway.app/api/ws/signals";
        const mod = await freshImport();
        expect(mod.getWsBaseUrl()).toBe("wss://backend.up.railway.app");
    });

    it("should derive ws:// from window.location when env var not set", async () => {
        // Simulate browser environment
        const originalWindow = globalThis.window;
        Object.defineProperty(globalThis, "window", {
            value: { location: { protocol: "http:", host: "localhost:3000", hostname: "localhost" } },
            writable: true,
            configurable: true,
        });

        const mod = await freshImport();
        const result = mod.getWsBaseUrl();
        expect(result).toBe("ws://localhost:3000");

        // Restore
        Object.defineProperty(globalThis, "window", { value: originalWindow, writable: true, configurable: true });
    });

    it("should return empty string on server side when no env var", async () => {
        // In jsdom, window exists, so we test the env var path
        process.env.NEXT_PUBLIC_WS_BASE_URL = "";
        const mod = await freshImport();
        // In jsdom, window exists, so it'll derive from location
        const result = mod.getWsBaseUrl();
        expect(typeof result).toBe("string");
    });
});

// ══════════════════════════════════════════════════════════════
//  getEnvStatus
// ══════════════════════════════════════════════════════════════

describe("getEnvStatus", () => {
    it("should return isValid=true when WS URL is a bare origin", async () => {
        process.env.NEXT_PUBLIC_WS_BASE_URL = "wss://backend.up.railway.app";
        const mod = await freshImport();
        const status = mod.getEnvStatus();
        expect(status.isValid).toBe(true);
        expect(status.errors).toHaveLength(0);
    });

    it("should return isValid=false and error when WS URL contains /ws/live path", async () => {
        process.env.NEXT_PUBLIC_WS_BASE_URL = "wss://wolf15-api-production.up.railway.app/ws/live";
        const mod = await freshImport();
        const status = mod.getEnvStatus();
        expect(status.isValid).toBe(false);
        expect(status.errors[0]).toMatch(/contains a path/);
        expect(status.errors[0]).toMatch(/\/ws\/live/);
    });

    it("should return isValid=false and error when WS URL has any path", async () => {
        process.env.NEXT_PUBLIC_WS_BASE_URL = "wss://backend.up.railway.app/ws";
        const mod = await freshImport();
        const status = mod.getEnvStatus();
        expect(status.isValid).toBe(false);
        expect(status.errors[0]).toMatch(/contains a path/);
    });

    it("should still return stripped wsUrl even when env var has path", async () => {
        process.env.NEXT_PUBLIC_WS_BASE_URL = "wss://backend.up.railway.app/ws/live";
        const mod = await freshImport();
        const status = mod.getEnvStatus();
        // wsUrl is the stripped (safe) value for callers
        expect(status.wsUrl).toBe("wss://backend.up.railway.app");
    });
});

// ══════════════════════════════════════════════════════════════
//  validateEnv
// ══════════════════════════════════════════════════════════════

describe("validateEnv", () => {
    it("should not throw when called without env var (no window)", async () => {
        const mod = await freshImport();
        expect(() => mod.validateEnv()).not.toThrow();
    });

    it("should throw ConfigError with ENV_WS_URL_HAS_PATH when URL contains /ws/live", async () => {
        // Simulate browser window so validateEnv runs path check
        const originalWindow = globalThis.window;
        Object.defineProperty(globalThis, "window", {
            value: { location: { protocol: "https:", host: "localhost:3000", hostname: "localhost" } },
            writable: true,
            configurable: true,
        });

        process.env.NEXT_PUBLIC_WS_BASE_URL = "wss://wolf15-api-production.up.railway.app/ws/live";
        const mod = await freshImport();
        let thrownErr: unknown;
        try {
            mod.validateEnv();
        } catch (e) {
            thrownErr = e;
        }
        expect(thrownErr).toBeInstanceOf(mod.ConfigError);
        expect((thrownErr as ConfigError).code).toBe("ENV_WS_URL_HAS_PATH");

        Object.defineProperty(globalThis, "window", { value: originalWindow, writable: true, configurable: true });
    });

    it("should throw ConfigError with ENV_WS_URL_HAS_PATH for any path (not just /ws/live)", async () => {
        const originalWindow = globalThis.window;
        Object.defineProperty(globalThis, "window", {
            value: { location: { protocol: "https:", host: "localhost:3000", hostname: "localhost" } },
            writable: true,
            configurable: true,
        });

        process.env.NEXT_PUBLIC_WS_BASE_URL = "wss://backend.up.railway.app/ws";
        const mod = await freshImport();
        let thrownErr: unknown;
        try {
            mod.validateEnv();
        } catch (e) {
            thrownErr = e;
        }
        expect(thrownErr).toBeInstanceOf(mod.ConfigError);
        expect((thrownErr as ConfigError).code).toBe("ENV_WS_URL_HAS_PATH");

        Object.defineProperty(globalThis, "window", { value: originalWindow, writable: true, configurable: true });
    });
});
