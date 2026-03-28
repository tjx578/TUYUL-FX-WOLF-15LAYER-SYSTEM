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

/** @internal — exported for unit testing only */
export function isVerdictLike(v: unknown): v is L12Verdict {
    return (
        v != null &&
        typeof v === "object" &&
        "symbol" in (v as Record<string, unknown>) &&
        ("verdict" in (v as Record<string, unknown>) || "confidence" in (v as Record<string, unknown>))
    );
}

/** @internal — exported for unit testing only */
export function normalizeVerdictResponse(
    data: L12Verdict[] | Record<string, L12Verdict> | undefined
): L12Verdict[] {
    if (!data) return [];
    if (Array.isArray(data)) return data;
    const obj = data as Record<string, unknown>;
    if ("verdicts" in obj) {
        const inner = obj.verdicts;
        if (Array.isArray(inner)) return inner as L12Verdict[];
        if (inner && typeof inner === "object") return Object.values(inner as Record<string, L12Verdict>);
    }
    // Handle wrapped responses like { data: [...], status: "ok", count: N }
    if ("data" in obj && Array.isArray(obj.data)) return obj.data as L12Verdict[];
    // Handle { results: [...] } wrapper
    if ("results" in obj && Array.isArray(obj.results)) return obj.results as L12Verdict[];
    // Last resort: only use Object.values if every value looks like a verdict (has symbol + verdict/confidence)
    const values = Object.values(obj);
    if (values.length > 0 && values.every(isVerdictLike)) {
        return values as L12Verdict[];
    }
    // Unknown shape — warn and return empty to avoid corrupt data
    if (values.length > 0) {
        console.warn("[verdicts.api] Unknown verdict response shape, returning empty array:", Object.keys(obj));
    }
    return [];
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
