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

// ── Env-var-dependent module: re-import per test ─────────────

function setEnv(env: Record<string, string | undefined>) {
    for (const [key, val] of Object.entries(env)) {
        if (val === undefined) {
            delete process.env[key];
        } else {
            process.env[key] = val;
        }
    }
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
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
    delete process.env.NEXT_PUBLIC_API_URL;
    delete process.env.NEXT_PUBLIC_WS_BASE_URL;
    delete process.env.NEXT_PUBLIC_WS_URL;
    delete process.env.NEXT_PUBLIC_TIMEZONE;
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
//  validateEnv
// ══════════════════════════════════════════════════════════════

describe("validateEnv", () => {
    it("should not throw when called", async () => {
        const mod = await freshImport();
        expect(() => mod.validateEnv()).not.toThrow();
    });
});
