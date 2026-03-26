/**
 * Regression test: useAccountStore getSnapshot() immutability.
 *
 * Verifies that:
 * 1. Every mutation produces a new object reference (so useSyncExternalStore re-renders).
 * 2. Snapshots are frozen (direct property writes throw in strict mode).
 * 3. emit() is called on every mutation (listener fires).
 */
import { describe, expect, it, vi } from "vitest";

// We test the store internals by importing the module and exercising the
// exported hook's mutation methods. Since useSyncExternalStore is a React hook,
// we mock it to just call getSnapshot() directly.
vi.mock("react", () => ({
    useSyncExternalStore: (subscribe: (l: () => void) => () => void, getSnapshot: () => unknown) => {
        // Register a no-op listener so subscribe/unsubscribe works
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

    it("snapshot is frozen — direct mutation throws", () => {
        const store = useAccountStore();
        expect(() => {
            store.trades["HACK"] = {} as never;
        }).toThrow();
    });

    it("emit() fires listener on every mutation", () => {
        const listener = vi.fn();

        // Access the subscribe function indirectly through a fresh module mock
        // that captures the listener
        let capturedSubscribe: ((l: () => void) => () => void) | null = null;
        vi.doMock("react", () => ({
            useSyncExternalStore: (sub: (l: () => void) => () => void, gs: () => unknown) => {
                capturedSubscribe = sub;
                return gs();
            },
        }));

        // Re-exercise the hook
        const store = useAccountStore();
        if (capturedSubscribe) {
            (capturedSubscribe as (l: () => void) => () => void)(listener);
        }

        listener.mockClear();
        store.setLatestPipelineResult({ symbol: "USDJPY" } as never);
        expect(listener).toHaveBeenCalledTimes(1);

        listener.mockClear();
        store.updateTrade({ trade_id: "T002", symbol: "AUDUSD" } as never);
        expect(listener).toHaveBeenCalledTimes(1);
    });
});
