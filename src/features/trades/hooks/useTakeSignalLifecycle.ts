"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchTakeSignalLifecycle } from "../api/trades.api";

export function useTakeSignalLifecycle(takeId: string | null) {
    const query = useQuery({
        queryKey: ["take-signal-lifecycle", takeId],
        queryFn: () => fetchTakeSignalLifecycle(takeId!),
        enabled: !!takeId,
        refetchInterval: 10_000,
    });

    return {
        data: query.data,
        isLoading: query.isLoading,
        isError: query.isError,
        error: query.error,
        refetch: query.refetch,
    };
}
