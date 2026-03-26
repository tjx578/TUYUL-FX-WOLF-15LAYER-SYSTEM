import type { L12Verdict, FreshnessClassLabel } from "@/types";
import type { SignalViewModel } from "./signal.types";

type ExtendedVerdict = L12Verdict & {
    signal_id?: string;
    verdict_id?: string;
};

function deriveHoldReason(verdict: L12Verdict): string | null {
    if (verdict.verdict !== "HOLD") return null;

    const failedGates = verdict.gates?.filter((g) => !g.passed) ?? [];
    if (failedGates.length === 0) return "HOLD with no explicit failed gate";
    return failedGates
        .map((g) => g.message || `${g.name} failed`)
        .join(" • ");
}

export function mapVerdictToSignalViewModel(
    verdict: L12Verdict,
    freshnessClass?: FreshnessClassLabel,
): SignalViewModel {
    const raw = verdict as ExtendedVerdict;

    return {
        id: raw.signal_id
            ? `signal:${raw.signal_id}`
            : `${verdict.symbol}:${verdict.timestamp}`,
        signalId: raw.signal_id,
        backendRefId: raw.verdict_id ?? raw.signal_id,
        symbol: verdict.symbol,
        verdict: verdict.verdict,
        confidence: verdict.confidence ?? 0,
        direction: verdict.direction,
        entryPrice: verdict.entry_price,
        stopLoss: verdict.stop_loss,
        takeProfit1: verdict.take_profit_1,
        takeProfit2: verdict.take_profit_2,
        riskRewardRatio: verdict.risk_reward_ratio,
        timestamp: verdict.timestamp,
        expiresAt: verdict.expires_at,
        freshnessClass,
        gates: (verdict.gates ?? []).map((g) => ({
            gateId: g.gate_id,
            name: g.name,
            passed: g.passed,
            value: g.value,
            threshold: g.threshold,
            message: g.message,
        })),
        scores: verdict.scores
            ? {
                wolfScore: verdict.scores.wolf_score,
                tiiScore: verdict.scores.tii_score,
                frpcScore: verdict.scores.frpc_score,
                regime: verdict.scores.regime,
                session: verdict.scores.session,
                confluenceScore: verdict.scores.confluence_score,
            }
            : undefined,
        holdReason: deriveHoldReason(verdict),
    };
}
