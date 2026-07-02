import type { L12Verdict, FreshnessClassLabel, PressurePriorityContext } from "@/types";
import type {
    SignalPressurePriorityContextViewModel,
    SignalPressurePriorityMemoryViewModel,
    SignalViewModel,
} from "./signal.types";

type ExtendedVerdict = L12Verdict & {
    signal_id?: string;
    verdict_id?: string;
};

function deriveHoldReason(verdict: L12Verdict): string | null {
    if (
        verdict.throttled_from ||
        verdict.effective_reason === "SIGNAL_THROTTLED" ||
        verdict.errors?.includes("SIGNAL_THROTTLED")
    ) {
        return `Signal throttled from ${verdict.throttled_from ?? "EXECUTE"} by engine throttle`;
    }

    if (verdict.verdict !== "HOLD") return null;

    if (verdict.last_hold_block_reason) return verdict.last_hold_block_reason;

    const failedGates = verdict.gates?.filter((g) => !g.passed) ?? [];
    if (failedGates.length === 0) return "HOLD with no explicit failed gate";
    return failedGates
        .map((g) => g.message || `${g.name} failed`)
        .join(" • ");
}

function optionalText(value: unknown): string | undefined {
    return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function optionalNumber(value: unknown): number | undefined {
    return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function optionalTextList(value: unknown): string[] | undefined {
    if (!Array.isArray(value)) return undefined;
    const items = value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
    return items.length ? items : undefined;
}

function mapPressureMemory(
    memory: PressurePriorityContext["fragmented_pressure_memory"],
): SignalPressurePriorityMemoryViewModel | undefined {
    if (!memory || typeof memory !== "object") return undefined;

    const mapped = {
        pressureMemoryScore: optionalNumber(memory.pressure_memory_score),
        sameSymbolReentryCount: optionalNumber(memory.same_symbol_reentry_count),
        interruptedByOtherSymbols: optionalNumber(memory.interrupted_by_other_symbols),
        cleanBlockCount: optionalNumber(memory.clean_block_count),
        maxCleanBlockMinutes: optionalNumber(memory.max_clean_block_minutes),
    };

    return Object.values(mapped).some((value) => value !== undefined) ? mapped : undefined;
}

function mapPressurePriorityContext(
    context: PressurePriorityContext | undefined,
): SignalPressurePriorityContextViewModel | undefined {
    const effectivePressureTier = optionalText(context?.effective_pressure_tier);
    if (!effectivePressureTier) return undefined;

    return {
        effectivePressureTier,
        tierScope: optionalText(context?.tier_scope),
        tierScore: optionalNumber(context?.tier_score),
        tierAction: optionalText(context?.tier_action),
        tierSourceEvent: optionalText(context?.tier_source_event),
        tierReasons: optionalTextList(context?.tier_reasons),
        impactTier: optionalText(context?.impact_tier),
        impactReasons: optionalTextList(context?.impact_reasons),
        lowEventHighImpactCandidate: context?.low_event_high_impact_candidate === true,
        tierIsExecutionSignal: context?.tier_is_execution_signal === true,
        tierExecutionImpact: context?.tier_execution_impact === true,
        fragmentedPressureMemory: mapPressureMemory(context?.fragmented_pressure_memory),
    };
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
        effectiveReason: verdict.effective_reason,
        throttledFrom: verdict.throttled_from,
        pressurePriorityContext: mapPressurePriorityContext(verdict.pressure_priority_context),
    };
}
