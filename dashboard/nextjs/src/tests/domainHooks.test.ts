/**
 * Signal Board Filters Hook & Trade Focus Filter Hook — PR-010
 *
 * Tests the filtering, sorting, and focus logic from the domain hooks.
 */
import { describe, expect, it } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSignalBoardFilters } from "@/features/signals/hooks/useSignalBoardFilters";
import { useTradeFocusFilter } from "@/features/trades/hooks/useTradeFocusFilter";
import type { SignalViewModel } from "@/features/signals/model/signal.types";
import { VerdictType } from "@/types";

function makeSignal(overrides: Partial<SignalViewModel> = {}): SignalViewModel {
    return {
        id: "sig-1",
        symbol: "EURUSD",
        verdict: VerdictType.EXECUTE,
        confidence: 0.85,
        timestamp: 1700000000,
        gates: [],
        holdReason: null,
        ...overrides,
    };
}

describe("useSignalBoardFilters", () => {
    const signals: SignalViewModel[] = [
        makeSignal({ id: "1", symbol: "EURUSD", verdict: VerdictType.EXECUTE, confidence: 0.9, timestamp: 100 }),
        makeSignal({ id: "2", symbol: "GBPUSD", verdict: VerdictType.HOLD, confidence: 0.7, timestamp: 200 }),
        makeSignal({ id: "3", symbol: "USDJPY", verdict: VerdictType.ABORT, confidence: 0.5, timestamp: 300 }),
        makeSignal({ id: "4", symbol: "EURJPY", verdict: VerdictType.EXECUTE_REDUCED_RISK, confidence: 0.8, timestamp: 150 }),
    ];

    it("returns all signals in default mode (ALL)", () => {
        const { result } = renderHook(() => useSignalBoardFilters(signals));
        expect(result.current.filteredSignals).toHaveLength(4);
        expect(result.current.mode).toBe("ALL");
        expect(result.current.query).toBe("");
    });

    it("sorts by confidence descending, then timestamp descending", () => {
        const { result } = renderHook(() => useSignalBoardFilters(signals));
        const ids = result.current.filteredSignals.map((s) => s.id);
        // confidence: 0.9, 0.8, 0.7, 0.5
        expect(ids).toEqual(["1", "4", "2", "3"]);
    });

    it("filters by EXECUTE mode (includes EXECUTE_REDUCED_RISK)", () => {
        const { result } = renderHook(() => useSignalBoardFilters(signals));

        act(() => {
            result.current.setMode("EXECUTE");
        });

        const verdicts = result.current.filteredSignals.map((s) => s.verdict);
        expect(verdicts).toEqual(["EXECUTE", "EXECUTE_REDUCED_RISK"]);
    });

    it("filters by HOLD mode", () => {
        const { result } = renderHook(() => useSignalBoardFilters(signals));

        act(() => {
            result.current.setMode("HOLD");
        });

        expect(result.current.filteredSignals).toHaveLength(1);
        expect(result.current.filteredSignals[0].verdict).toBe("HOLD");
    });

    it("filters by ABORT mode", () => {
        const { result } = renderHook(() => useSignalBoardFilters(signals));

        act(() => {
            result.current.setMode("ABORT");
        });

        expect(result.current.filteredSignals).toHaveLength(1);
        expect(result.current.filteredSignals[0].verdict).toBe("ABORT");
    });

    it("filters by symbol query (case-insensitive)", () => {
        const { result } = renderHook(() => useSignalBoardFilters(signals));

        act(() => {
            result.current.setQuery("eur");
        });

        const symbols = result.current.filteredSignals.map((s) => s.symbol);
        expect(symbols).toEqual(expect.arrayContaining(["EURUSD", "EURJPY"]));
        expect(symbols).toHaveLength(2);
    });

    it("combines mode and query filters", () => {
        const { result } = renderHook(() => useSignalBoardFilters(signals));

        act(() => {
            result.current.setMode("EXECUTE");
            result.current.setQuery("eur");
        });

        expect(result.current.filteredSignals).toHaveLength(2);
    });

    it("returns empty when no signals match", () => {
        const { result } = renderHook(() => useSignalBoardFilters(signals));

        act(() => {
            result.current.setQuery("XYZABC");
        });

        expect(result.current.filteredSignals).toHaveLength(0);
    });
});

describe("useTradeFocusFilter", () => {
    const trades = [
        { trade_id: "t1", account_id: "acc-1", signal_id: "sig-1" },
        { trade_id: "t2", account_id: "acc-2", signal_id: "sig-1" },
        { trade_id: "t3", account_id: "acc-1", signal_id: "sig-2" },
    ];

    it("returns all trades when no focus is applied", () => {
        const { result } = renderHook(() =>
            useTradeFocusFilter(trades, { accountId: null, signalId: null }),
        );
        expect(result.current).toHaveLength(3);
    });

    it("filters by accountId", () => {
        const { result } = renderHook(() =>
            useTradeFocusFilter(trades, { accountId: "acc-1", signalId: null }),
        );
        expect(result.current).toHaveLength(2);
        expect(result.current.every((t) => t.account_id === "acc-1")).toBe(true);
    });

    it("filters by signalId", () => {
        const { result } = renderHook(() =>
            useTradeFocusFilter(trades, { accountId: null, signalId: "sig-1" }),
        );
        expect(result.current).toHaveLength(2);
        expect(result.current.every((t) => t.signal_id === "sig-1")).toBe(true);
    });

    it("combines accountId and signalId focus", () => {
        const { result } = renderHook(() =>
            useTradeFocusFilter(trades, { accountId: "acc-1", signalId: "sig-1" }),
        );
        expect(result.current).toHaveLength(1);
        expect(result.current[0].trade_id).toBe("t1");
    });
});
