/**
 * Unit tests for lib/auth.ts
 *
 * Tests:
 *  - getToken / setToken / removeToken lifecycle
 *  - hasRole membership check
 *  - bearerHeader format
 *  - getTransportToken alias
 *  - fetchWsTicket fallback chain
 *  - Server-side (no window) guards
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// ── LocalStorage mock ────────────────────────────────────────

const storageMap = new Map<string, string>();
const localStorageMock = {
    getItem: vi.fn((key: string) => storageMap.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => storageMap.set(key, value)),
    removeItem: vi.fn((key: string) => storageMap.delete(key)),
    clear: vi.fn(() => storageMap.clear()),
    get length() { return storageMap.size; },
    key: vi.fn(() => null),
};

beforeEach(() => {
    storageMap.clear();
    clearWsTicketCache();
    Object.defineProperty(globalThis, "localStorage", { value: localStorageMock, writable: true });
});

afterEach(() => {
    vi.restoreAllMocks();
});

// ── Import AFTER mock setup ──────────────────────────────────

import {
    getToken,
    setToken,
    removeToken,
    hasRole,
    bearerHeader,
    getTransportToken,
    fetchWsTicket,
    clearWsTicketCache,
    ADMIN_ROLES,
} from "@/lib/auth";

// ══════════════════════════════════════════════════════════════
//  Token Storage
// ══════════════════════════════════════════════════════════════

describe("Token storage", () => {
    it("should return null when no token is stored", () => {
        expect(getToken()).toBeNull();
    });

    it("should store and retrieve a token", () => {
        setToken("my-jwt-123");
        expect(getToken()).toBe("my-jwt-123");
    });

    it("should remove a stored token", () => {
        setToken("my-jwt-123");
        removeToken();
        expect(getToken()).toBeNull();
    });
});

// ══════════════════════════════════════════════════════════════
//  hasRole
// ══════════════════════════════════════════════════════════════

describe("hasRole", () => {
    it("should return true when role is in the allowed list", () => {
        expect(hasRole("operator", ["operator", "viewer"])).toBe(true);
    });

    it("should return false when role is not in the allowed list", () => {
        expect(hasRole("viewer", ["operator"])).toBe(false);
    });

    it("should return false for undefined role", () => {
        expect(hasRole(undefined, ["operator"])).toBe(false);
    });

    it("should export ADMIN_ROLES constant", () => {
        expect(ADMIN_ROLES).toEqual(["risk_admin", "config_admin", "approver"]);
    });

    it("should work with ADMIN_ROLES for role check", () => {
        expect(hasRole("risk_admin", ADMIN_ROLES)).toBe(true);
        expect(hasRole("viewer", ADMIN_ROLES)).toBe(false);
    });
});

// ══════════════════════════════════════════════════════════════
//  bearerHeader
// ══════════════════════════════════════════════════════════════

describe("bearerHeader", () => {
    it("should return Bearer token when token exists", () => {
        setToken("jwt-abc");
        expect(bearerHeader()).toBe("Bearer jwt-abc");
    });

    it("should return undefined when no token exists", () => {
        expect(bearerHeader()).toBeUndefined();
    });
});

// ══════════════════════════════════════════════════════════════
//  getTransportToken
// ══════════════════════════════════════════════════════════════

describe("getTransportToken", () => {
    it("should return the same value as getToken", () => {
        setToken("transport-123");
        expect(getTransportToken()).toBe("transport-123");
    });

    it("should return null when no token", () => {
        expect(getTransportToken()).toBeNull();
    });
});

// ══════════════════════════════════════════════════════════════
//  fetchWsTicket
// ══════════════════════════════════════════════════════════════

describe("fetchWsTicket", () => {
    it("should return JWT from localStorage if available (no fetch needed)", async () => {
        setToken("local-jwt");
        const ticket = await fetchWsTicket();
        expect(ticket).toBe("local-jwt");
    });

    it("should fetch from /api/auth/ws-ticket when no local token", async () => {
        const mockFetch = vi.fn().mockResolvedValue({
            ok: true,
            json: async () => ({ token: "server-ticket" }),
        });
        globalThis.fetch = mockFetch;

        const ticket = await fetchWsTicket();
        expect(ticket).toBe("server-ticket");
        expect(mockFetch).toHaveBeenCalledWith("/api/auth/ws-ticket");
    });

    it("should return null when fetch fails", async () => {
        globalThis.fetch = vi.fn().mockResolvedValue({ ok: false });

        const ticket = await fetchWsTicket();
        expect(ticket).toBeNull();
    });

    it("should return null when fetch throws", async () => {
        globalThis.fetch = vi.fn().mockRejectedValue(new Error("Network error"));

        const ticket = await fetchWsTicket();
        expect(ticket).toBeNull();
    });
});
