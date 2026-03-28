/**
 * Regression test: useAccountStore getSnapshot() immutability.
 *
 * Verifies that:
 * 1. Every mutation produces a new object reference (so useSyncExternalStore re-renders).
 * 2. Mutations create a new trades reference (copy-on-write — inner object is replaced).
 * 3. emit() is called on every mutation (listener fires).
 */
import { describe, expect, it, vi } from "vitest";

// Capture the store's subscribe function so we can register listeners in tests.
let capturedSubscribe: ((l: () => void) => () => void) | null = null;

// We test the store internals by importing the module and exercising the
// exported hook's mutation methods. Since useSyncExternalStore is a React hook,
// we mock it to call getSnapshot() directly and capture the subscribe handle.
vi.mock("react", () => ({
    useSyncExternalStore: (subscribe: (l: () => void) => () => void, getSnapshot: () => unknown) => {
        // Capture on first call so tests can register listeners directly.
        if (!capturedSubscribe) capturedSubscribe = subscribe;
        // Register a no-op so subscribe/unsubscribe path is exercised.
        subscribe(() => { });
        return getSnapshot();
    },
}));

import { useAccountStore } from "@/store/useAccountStore";

describe("useAccountStore getSnapshot() immutability", () => {
    it("setLatestPipelineResult produces a new snapshot reference", () => {
        const store1 = useAccountStore();
        const snap1 = { latestPipelineResult: store1.latestPipelineResult, trades: store1.trades };

        store1.setLatestPipelineResult({ symbol: "EURUSD" } as never);

        const store2 = useAccountStore();
        const snap2 = { latestPipelineResult: store2.latestPipelineResult, trades: store2.trades };

        // New reference — Object.is must be false
        expect(snap1.latestPipelineResult).not.toBe(snap2.latestPipelineResult);
        expect(snap2.latestPipelineResult).toEqual({ symbol: "EURUSD" });
    });

    it("updateTrade produces a new snapshot reference", () => {
        const store1 = useAccountStore();
        const tradesRef1 = store1.trades;

        store1.updateTrade({ trade_id: "T001", symbol: "GBPUSD" } as never);

        const store2 = useAccountStore();
        const tradesRef2 = store2.trades;

        // Trades object reference must differ
        expect(tradesRef1).not.toBe(tradesRef2);
        expect(tradesRef2["T001"]).toEqual({ trade_id: "T001", symbol: "GBPUSD" });
    });

    it("mutations create a new trades reference (copy-on-write)", () => {
        // The store replaces snapshot.trades with a new object on each updateTrade call.
        // This ensures useSyncExternalStore consumers detect the change via reference equality.
        const before = useAccountStore().trades;
        useAccountStore().updateTrade({ trade_id: "T-IMM", symbol: "XAUUSD" } as never);
        const after = useAccountStore().trades;

        // updateTrade spreads the old trades into a new object — references must differ
        expect(before).not.toBe(after);
        expect(after["T-IMM"]).toBeDefined();
    });

    it("emit() fires listener on every mutation", () => {
        const listener = vi.fn();

        // capturedSubscribe is set by vi.mock setup during the first useAccountStore() call above.
        expect(capturedSubscribe).not.toBeNull();
        const unsubscribe = (capturedSubscribe as (l: () => void) => () => void)(listener);

        listener.mockClear();
        useAccountStore().setLatestPipelineResult({ symbol: "USDJPY" } as never);
        expect(listener).toHaveBeenCalledTimes(1);

        listener.mockClear();
        useAccountStore().updateTrade({ trade_id: "T002", symbol: "AUDUSD" } as never);
        expect(listener).toHaveBeenCalledTimes(1);

        unsubscribe();
    });
});
