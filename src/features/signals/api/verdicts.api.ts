import type { L12Verdict } from "@/types";
import { useApiQuery, apiMutate, API_ENDPOINTS } from "@/shared/api/client";

export interface TakeSignalRequest {
    verdict_id: string;
    accounts: string[];
    pair: string;
    direction: "BUY" | "SELL";
    entry: number;
    sl: number;
    tp: number;
    risk_percent: number;
    operator?: string;
}

export interface RiskPreviewMultiRequest {
    verdict_id: string;
    accounts: Array<{ account_id: string }>;
    risk_percent: number;
    risk_mode: "FIXED" | "SPLIT";
}

export interface RiskPreviewAccountItem {
    account_id: string;
    lot_size: number;
    risk_percent: number;
    daily_dd_after: number;
    allowed: boolean;
    reason?: string;
}

export interface SkipSignalRequest {
    signal_id: string;
    pair?: string;
    reason?: string;
}

function normalizeVerdictResponse(
    data: L12Verdict[] | Record<string, L12Verdict> | undefined
): L12Verdict[] {
    if (!data) return [];
    if (Array.isArray(data)) return data;
    if ("verdicts" in data) {
        const inner = (data as Record<string, unknown>).verdicts;
        if (Array.isArray(inner)) return inner as L12Verdict[];
        if (inner && typeof inner === "object") return Object.values(inner as Record<string, L12Verdict>);
    }
    return Object.values(data);
}

export function useAllVerdicts(options?: { refreshInterval?: number }) {
    const { data, error, isLoading, mutate } = useApiQuery<L12Verdict[] | Record<string, L12Verdict>>(
        API_ENDPOINTS.verdictAll,
        options?.refreshInterval ? { refetchInterval: options.refreshInterval } : undefined,
    );
    const normalized = normalizeVerdictResponse(data);
    return { data: normalized, isLoading, isError: !!error, error, mutate };
}

export async function takeSignal(req: TakeSignalRequest): Promise<void> {
    await apiMutate("/api/v1/signals/take", req);
}

export async function previewRiskMulti(
    req: RiskPreviewMultiRequest
): Promise<{ previews: RiskPreviewAccountItem[] }> {
    return apiMutate(API_ENDPOINTS.riskPreviewMulti, req);
}

export async function skipSignal(req: SkipSignalRequest): Promise<void> {
    await apiMutate("/api/v1/signals/skip", req);
}
