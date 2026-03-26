/**
 * Signal Constants & Verdict Classifiers — PR-010
 *
 * Tests isExecuteVerdict, isHoldVerdict, isAbortVerdict,
 * and SIGNAL_FILTER_MODES from the signals domain model.
 */
import { describe, expect, it } from "vitest";
import {
    SIGNAL_FILTER_MODES,
    isExecuteVerdict,
    isHoldVerdict,
    isAbortVerdict,
} from "@/features/signals/model/signal.constants";

describe("SIGNAL_FILTER_MODES", () => {
    it("contains exactly the 4 expected modes", () => {
        expect(SIGNAL_FILTER_MODES).toEqual(["ALL", "EXECUTE", "HOLD", "ABORT"]);
    });
});

describe("isExecuteVerdict", () => {
    it("returns true for EXECUTE", () => {
        expect(isExecuteVerdict("EXECUTE")).toBe(true);
    });

    it("returns true for EXECUTE_REDUCED_RISK", () => {
        expect(isExecuteVerdict("EXECUTE_REDUCED_RISK")).toBe(true);
    });

    it("returns false for HOLD", () => {
        expect(isExecuteVerdict("HOLD")).toBe(false);
    });

    it("returns false for ABORT", () => {
        expect(isExecuteVerdict("ABORT")).toBe(false);
    });

    it("returns false for NO_TRADE", () => {
        expect(isExecuteVerdict("NO_TRADE")).toBe(false);
    });
});

describe("isHoldVerdict", () => {
    it("returns true for HOLD", () => {
        expect(isHoldVerdict("HOLD")).toBe(true);
    });

    it("returns false for EXECUTE", () => {
        expect(isHoldVerdict("EXECUTE")).toBe(false);
    });

    it("returns false for ABORT", () => {
        expect(isHoldVerdict("ABORT")).toBe(false);
    });
});

describe("isAbortVerdict", () => {
    it("returns true for ABORT", () => {
        expect(isAbortVerdict("ABORT")).toBe(true);
    });

    it("returns false for EXECUTE", () => {
        expect(isAbortVerdict("EXECUTE")).toBe(false);
    });

    it("returns false for HOLD", () => {
        expect(isAbortVerdict("HOLD")).toBe(false);
    });
});
