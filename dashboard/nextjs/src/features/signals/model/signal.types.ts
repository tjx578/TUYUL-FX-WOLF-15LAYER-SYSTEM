import type { VerdictType, FreshnessClassLabel } from "@/types";

export type SignalFilterMode = "ALL" | "EXECUTE" | "HOLD" | "ABORT";

export interface SignalGateViewModel {
    gateId: string;
    name: string;
    passed: boolean;
    value?: number | string;
    threshold?: number | string;
    message?: string;
}

export interface SignalScoreViewModel {
    wolfScore?: number;
    tiiScore?: number;
    frpcScore?: number;
    regime?: string;
    session?: string;
    confluenceScore?: number;
}

export interface SignalViewModel {
    id: string;
    signalId?: string;
    backendRefId?: string;
    symbol: string;
    verdict: VerdictType;
    confidence: number;
    direction?: "BUY" | "SELL";
    entryPrice?: number;
    stopLoss?: number;
    takeProfit1?: number;
    takeProfit2?: number;
    riskRewardRatio?: number;
    timestamp: number;
    expiresAt?: number;
    freshnessClass?: FreshnessClassLabel;
    gates: SignalGateViewModel[];
    scores?: SignalScoreViewModel;
    holdReason?: string | null;

    optimisticTakeStatus?: "IDLE" | "SUBMITTING" | "SUBMITTED";
}

export interface SignalBoardState {
    signals: SignalViewModel[];
    isLoading: boolean;
    isError: boolean;
    error?: unknown;
    wsStatus: string;
    isStale: boolean;
    lastUpdatedAt: number | null;
    freshnessClass?: FreshnessClassLabel;
}
