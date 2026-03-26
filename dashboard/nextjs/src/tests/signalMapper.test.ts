/**
 * Signal Mapper Tests — PR-010
 *
 * Tests mapVerdictToSignalViewModel pure function for correct field mapping,
 * hold-reason derivation, and edge cases.
 */
import { describe, expect, it } from "vitest";
import { mapVerdictToSignalViewModel } from "@/features/signals/model/signal.mapper";
import type { L12Verdict, FreshnessClassLabel } from "@/types";
import { VerdictType } from "@/types";

function makeVerdict(overrides: Partial<L12Verdict> = {}): L12Verdict {
    return {
        symbol: "EURUSD",
        verdict: VerdictType.EXECUTE,
        confidence: 0.85,
        timestamp: 1700000000,
        direction: "BUY",
        entry_price: 1.1,
        stop_loss: 1.095,
        take_profit_1: 1.11,
        take_profit_2: 1.12,
        risk_reward_ratio: 2.0,
        expires_at: 1700003600,
        gates: [
            { gate_id: "g1", name: "TII Gate", passed: true, value: 0.95, threshold: 0.9 },
            { gate_id: "g2", name: "FRPC Gate", passed: true, value: 0.94, threshold: 0.93 },
        ],
        scores: {
            wolf_score: 0.78,
            tii_score: 0.95,
            frpc_score: 0.94,
            regime: "TRENDING",
            session: "LONDON",
            confluence_score: 0.88,
        },
        ...overrides,
    } as L12Verdict;
}

describe("mapVerdictToSignalViewModel", () => {
    it("maps basic fields correctly", () => {
        const verdict = makeVerdict();
        const vm = mapVerdictToSignalViewModel(verdict);

        expect(vm.symbol).toBe("EURUSD");
        expect(vm.verdict).toBe("EXECUTE");
        expect(vm.confidence).toBe(0.85);
        expect(vm.direction).toBe("BUY");
        expect(vm.entryPrice).toBe(1.1);
        expect(vm.stopLoss).toBe(1.095);
        expect(vm.takeProfit1).toBe(1.11);
        expect(vm.takeProfit2).toBe(1.12);
        expect(vm.riskRewardRatio).toBe(2.0);
        expect(vm.timestamp).toBe(1700000000);
        expect(vm.expiresAt).toBe(1700003600);
    });

    it("maps gates from snake_case to camelCase", () => {
        const verdict = makeVerdict();
        const vm = mapVerdictToSignalViewModel(verdict);

        expect(vm.gates).toHaveLength(2);
        expect(vm.gates[0]).toEqual({
            gateId: "g1",
            name: "TII Gate",
            passed: true,
            value: 0.95,
            threshold: 0.9,
        });
    });

    it("maps scores from snake_case to camelCase", () => {
        const verdict = makeVerdict();
        const vm = mapVerdictToSignalViewModel(verdict);

        expect(vm.scores).toEqual({
            wolfScore: 0.78,
            tiiScore: 0.95,
            frpcScore: 0.94,
            regime: "TRENDING",
            session: "LONDON",
            confluenceScore: 0.88,
        });
    });

    it("generates ID from symbol + timestamp when no signal_id", () => {
        const verdict = makeVerdict();
        const vm = mapVerdictToSignalViewModel(verdict);

        expect(vm.id).toBe("EURUSD:1700000000");
        expect(vm.signalId).toBeUndefined();
    });

    it("uses signal_id for ID when present", () => {
        const verdict = makeVerdict();
        (verdict as unknown as Record<string, unknown>).signal_id = "sig-123";

        const vm = mapVerdictToSignalViewModel(verdict);
        expect(vm.id).toBe("signal:sig-123");
        expect(vm.signalId).toBe("sig-123");
    });

    it("derives holdReason from failed gates for HOLD verdict", () => {
        const verdict = makeVerdict({
            verdict: VerdictType.HOLD,
            gates: [
                { gate_id: "g1", name: "TII Gate", passed: false, message: "TII below threshold" },
                { gate_id: "g2", name: "FRPC Gate", passed: true },
            ],
        });

        const vm = mapVerdictToSignalViewModel(verdict);
        expect(vm.holdReason).toBe("TII below threshold");
    });

    it("returns null holdReason for non-HOLD verdict", () => {
        const verdict = makeVerdict({ verdict: VerdictType.EXECUTE });
        const vm = mapVerdictToSignalViewModel(verdict);
        expect(vm.holdReason).toBeNull();
    });

    it("handles HOLD with no failed gates gracefully", () => {
        const verdict = makeVerdict({
            verdict: VerdictType.HOLD,
            gates: [{ gate_id: "g1", name: "Gate", passed: true }],
        });

        const vm = mapVerdictToSignalViewModel(verdict);
        expect(vm.holdReason).toBe("HOLD with no explicit failed gate");
    });

    it("applies freshnessClass when passed", () => {
        const verdict = makeVerdict();
        const vm = mapVerdictToSignalViewModel(verdict, "LIVE" as FreshnessClassLabel);
        expect(vm.freshnessClass).toBe("LIVE");
    });

    it("handles missing scores gracefully", () => {
        const verdict = makeVerdict({ scores: undefined });
        const vm = mapVerdictToSignalViewModel(verdict);
        expect(vm.scores).toBeUndefined();
    });

    it("handles missing gates gracefully", () => {
        const verdict = makeVerdict({ gates: undefined });
        const vm = mapVerdictToSignalViewModel(verdict);
        expect(vm.gates).toEqual([]);
    });

    it("defaults confidence to 0 when missing", () => {
        const verdict = makeVerdict({ confidence: undefined });
        const vm = mapVerdictToSignalViewModel(verdict);
        expect(vm.confidence).toBe(0);
    });
});
