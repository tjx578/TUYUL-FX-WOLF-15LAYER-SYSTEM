import type { Trade } from "@/types";
import { useApiQuery, apiMutate, apiMutateWithHeaders, API_ENDPOINTS, POLL_INTERVALS } from "@/shared/api/client";

export interface ActiveTradesResponse {
    trades: Trade[];
    count: number;
}

export function useActiveTrades() {
    const { data, error, isLoading, mutate } = useApiQuery<
        ActiveTradesResponse | Trade[]
    >(
        API_ENDPOINTS.tradesActive,
        { refetchInterval: POLL_INTERVALS.trades },
    );
    return { data, isLoading, isError: !!error, error, mutate };
}

export async function confirmTrade(tradeId: string): Promise<void> {
    await apiMutateWithHeaders(
        API_ENDPOINTS.tradesConfirmById(tradeId),
        undefined,
        "POST",
        { "X-Idempotency-Key": `confirm:${tradeId}` }
    );
}

export async function closeTrade(tradeId: string, reason: string): Promise<void> {
    await apiMutate(API_ENDPOINTS.tradesClose, { trade_id: tradeId, reason });
}
