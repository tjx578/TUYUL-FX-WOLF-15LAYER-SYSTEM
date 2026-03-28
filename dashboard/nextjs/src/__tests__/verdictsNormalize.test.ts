/**
 * Unit tests for normalizeVerdictResponse and isVerdictLike in verdicts.api.ts.
 *
 * These cover the BUG-06 fix: the API can return verdicts in multiple shapes
 * ({data:[...]}, {results:[...]}, {verdicts:{...}}, plain array, object map)
 * and normalizeVerdictResponse must handle all of them without corrupting data.
 */

import { vi, describe, it, expect } from "vitest";

// Mock the API client so we can import verdicts.api.ts in isolation
vi.mock("@/shared/api/client", () => ({
    useApiQuery: vi.fn(),
    apiMutate: vi.fn(),
    API_ENDPOINTS: {
        verdictAll: "/api/v1/verdicts/all",
        riskPreviewMulti: "/api/v1/risk/preview/multi",
    },
}));

import { normalizeVerdictResponse, isVerdictLike } from "@/features/signals/api/verdicts.api";
import type { L12Verdict } from "@/types";
import { VerdictType } from "@/types";

// ── Helpers ──────────────────────────────────────────────────

function makeVerdict(overrides: Partial<L12Verdict> = {}): L12Verdict {
    return {
        symbol: "EURUSD",
        verdict: "EXECUTE",
        confidence: 0.85,
        timestamp: 1700000000,
        ...overrides,
    } as L12Verdict;
}

// ══════════════════════════════════════════════════════════════
//  isVerdictLike
// ══════════════════════════════════════════════════════════════

describe("isVerdictLike", () => {
    it("returns true for an object with symbol + verdict", () => {
        expect(isVerdictLike({ symbol: "EURUSD", verdict: "EXECUTE" })).toBe(true);
    });

    it("returns true for an object with symbol + confidence", () => {
        expect(isVerdictLike({ symbol: "GBPUSD", confidence: 0.9 })).toBe(true);
    });

    it("returns false for an object missing symbol", () => {
        expect(isVerdictLike({ verdict: "EXECUTE" })).toBe(false);
    });

    it("returns false for null", () => {
        expect(isVerdictLike(null)).toBe(false);
    });

    it("returns false for a primitive", () => {
        expect(isVerdictLike("EURUSD")).toBe(false);
        expect(isVerdictLike(42)).toBe(false);
    });

    it("returns false for an empty object", () => {
        expect(isVerdictLike({})).toBe(false);
    });
});

// ══════════════════════════════════════════════════════════════
//  normalizeVerdictResponse — BUG-06 regression coverage
// ══════════════════════════════════════════════════════════════

describe("normalizeVerdictResponse", () => {
    const v1 = makeVerdict({ symbol: "EURUSD" });
    const v2 = makeVerdict({ symbol: "GBPUSD", verdict: VerdictType.HOLD });

    it("returns [] for undefined input", () => {
        expect(normalizeVerdictResponse(undefined)).toEqual([]);
    });

    it("returns the array as-is for a plain array", () => {
        const result = normalizeVerdictResponse([v1, v2]);
        expect(result).toHaveLength(2);
        expect(result[0].symbol).toBe("EURUSD");
    });

    it("handles { verdicts: [...] } wrapper", () => {
        const result = normalizeVerdictResponse({ verdicts: [v1, v2] } as never);
        expect(result).toHaveLength(2);
    });

    it("handles { verdicts: { key: verdict } } object map", () => {
        const result = normalizeVerdictResponse({ verdicts: { a: v1, b: v2 } } as never);
        expect(result).toHaveLength(2);
    });

    it("handles { data: [...] } wrapper — BUG-06 specific", () => {
        const result = normalizeVerdictResponse({ data: [v1, v2] } as never);
        expect(result).toHaveLength(2);
        expect(result[0].symbol).toBe("EURUSD");
    });

    it("handles { results: [...] } wrapper", () => {
        const result = normalizeVerdictResponse({ results: [v1] } as never);
        expect(result).toHaveLength(1);
    });

    it("handles object map where all values are verdict-like", () => {
        const result = normalizeVerdictResponse({ EURUSD: v1, GBPUSD: v2 } as never);
        expect(result).toHaveLength(2);
    });

    it("returns [] for object map where values are NOT verdict-like", () => {
        const result = normalizeVerdictResponse({ a: "not-a-verdict", b: 42 } as never);
        expect(result).toEqual([]);
    });

    it("does not throw for { data: [...] } when data is non-array (returns empty)", () => {
        // data key exists but is not an array — falls through to Object.values check
        const result = normalizeVerdictResponse({ data: "bad" } as never);
        expect(result).toEqual([]);
    });

    it("returns [] for an empty array", () => {
        expect(normalizeVerdictResponse([])).toEqual([]);
    });

    it("returns [] for an empty object", () => {
        expect(normalizeVerdictResponse({} as never)).toEqual([]);
    });

    it("preserves all fields on individual verdicts", () => {
        const full = makeVerdict({ symbol: "USDJPY", verdict: VerdictType.ABORT, confidence: 0.3 });
        const [result] = normalizeVerdictResponse([full]);
        expect(result.symbol).toBe("USDJPY");
        expect(result.verdict).toBe(VerdictType.ABORT);
        expect(result.confidence).toBe(0.3);
    });
});
