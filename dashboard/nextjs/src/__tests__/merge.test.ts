/**
 * Unit tests for lib/realtime/merge.ts
 *
 * Tests:
 *  - mergeMap: delta overrides snapshot, preserves untouched keys
 *  - mergeSingle: timestamp-guarded merge, stale delta discard
 *  - mergeList: upsert by identity key, insert when missing
 */

import { describe, it, expect } from "vitest";
import { mergeMap, mergeSingle, mergeList } from "@/lib/realtime/merge";

// ══════════════════════════════════════════════════════════════
//  mergeMap
// ══════════════════════════════════════════════════════════════

describe("mergeMap", () => {
    it("should override snapshot keys with delta keys", () => {
        const snapshot = { EURUSD: 1.1, GBPUSD: 1.3 };
        const delta = { EURUSD: 1.105 };
        const result = mergeMap(snapshot, delta);

        expect(result.EURUSD).toBe(1.105);
        expect(result.GBPUSD).toBe(1.3);
    });

    it("should add new keys from delta", () => {
        const snapshot = { EURUSD: 1.1 };
        const delta = { USDJPY: 150.5 };
        const result = mergeMap(snapshot, delta);

        expect(result.EURUSD).toBe(1.1);
        expect(result.USDJPY).toBe(150.5);
    });

    it("should return identical result when delta is empty", () => {
        const snapshot = { EURUSD: 1.1 };
        const result = mergeMap(snapshot, {});

        expect(result).toEqual(snapshot);
    });

    it("should handle empty snapshot with delta producing new keys", () => {
        const result = mergeMap({} as Record<string, number>, { EURUSD: 1.1 });
        expect(result).toEqual({ EURUSD: 1.1 });
    });
});

// ══════════════════════════════════════════════════════════════
//  mergeSingle
// ══════════════════════════════════════════════════════════════

describe("mergeSingle", () => {
    it("should return delta when snapshot is null", () => {
        const delta = { value: 100, timestamp: 1000 };
        expect(mergeSingle(null, delta)).toBe(delta);
    });

    it("should accept delta with newer timestamp (numeric)", () => {
        const snapshot = { value: 100, timestamp: 1000 };
        const delta = { value: 200, timestamp: 2000 };
        expect(mergeSingle(snapshot, delta)).toBe(delta);
    });

    it("should discard delta with older timestamp (stale guard)", () => {
        const snapshot = { value: 100, timestamp: 2000 };
        const delta = { value: 200, timestamp: 1000 };
        expect(mergeSingle(snapshot, delta)).toBe(snapshot);
    });

    it("should accept delta with equal timestamp", () => {
        const snapshot = { value: 100, timestamp: 1000 };
        const delta = { value: 200, timestamp: 1000 };
        // Equal timestamp → delta is not stale (deltaTime < snapshotTime is false)
        expect(mergeSingle(snapshot, delta)).toBe(delta);
    });

    it("should handle string ISO timestamps", () => {
        const snapshot = { value: 100, timestamp: "2025-01-01T00:00:00Z" };
        const delta = { value: 200, timestamp: "2025-06-01T00:00:00Z" };
        expect(mergeSingle(snapshot, delta)).toBe(delta);
    });

    it("should discard stale delta with string ISO timestamps", () => {
        const snapshot = { value: 100, timestamp: "2025-06-01T00:00:00Z" };
        const delta = { value: 200, timestamp: "2025-01-01T00:00:00Z" };
        expect(mergeSingle(snapshot, delta)).toBe(snapshot);
    });

    it("should handle missing timestamp gracefully (treated as 0)", () => {
        const snapshot = { value: 100 };
        const delta = { value: 200 };
        // Both timestamps default to 0, 0 < 0 is false → delta wins
        expect(mergeSingle(snapshot, delta)).toBe(delta);
    });
});

// ══════════════════════════════════════════════════════════════
//  mergeList
// ══════════════════════════════════════════════════════════════

describe("mergeList", () => {
    const getKey = (item: { id: string }) => item.id;

    it("should upsert an existing item by key", () => {
        const snapshot = [
            { id: "A", value: 1 },
            { id: "B", value: 2 },
        ];
        const delta = { id: "B", value: 99 };

        const result = mergeList(snapshot, delta, getKey);
        expect(result).toHaveLength(2);
        expect(result[1]).toEqual({ id: "B", value: 99 });
    });

    it("should append new item when key not found in snapshot", () => {
        const snapshot = [{ id: "A", value: 1 }];
        const delta = { id: "C", value: 3 };

        const result = mergeList(snapshot, delta, getKey);
        expect(result).toHaveLength(2);
        expect(result[1]).toEqual({ id: "C", value: 3 });
    });

    it("should preserve unaffected items", () => {
        const snapshot = [
            { id: "A", value: 1 },
            { id: "B", value: 2 },
            { id: "C", value: 3 },
        ];
        const delta = { id: "B", value: 99 };

        const result = mergeList(snapshot, delta, getKey);
        expect(result[0]).toEqual({ id: "A", value: 1 });
        expect(result[2]).toEqual({ id: "C", value: 3 });
    });

    it("should use default key extractor (x.id) when no getKey provided", () => {
        const snapshot = [{ id: "A", val: 1 }];
        const delta = { id: "A", val: 99 };

        const result = mergeList(snapshot, delta);
        expect(result[0]).toEqual({ id: "A", val: 99 });
    });

    it("should append when key extractor returns undefined", () => {
        const snapshot = [{ name: "A" }];
        const delta = { name: "B" };
        // Default getKey returns undefined for objects without `id`
        const result = mergeList(snapshot, delta);
        expect(result).toHaveLength(2);
    });

    it("should not mutate original snapshot array", () => {
        const snapshot = [{ id: "A", value: 1 }];
        const original = [...snapshot];
        mergeList(snapshot, { id: "A", value: 99 }, getKey);
        expect(snapshot).toEqual(original);
    });
});
