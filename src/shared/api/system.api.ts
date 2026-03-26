"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/fetcher";
import type { OrchestratorState, SystemHealth } from "@/types";

export const SYSTEM_ENDPOINTS = {
    health: "/api/health",
    orchestratorState: "/api/v1/orchestrator/state",
} as const;

async function systemFetcher<T>(url: string): Promise<T> {
    const res = await apiFetch(url);
    if (!res.ok) {
        throw new Error(`Request failed: ${res.status} ${res.statusText}`);
    }
    return res.json() as Promise<T>;
}

export function useHealth() {
    const { data, error, isLoading } = useQuery<SystemHealth>({
        queryKey: [SYSTEM_ENDPOINTS.health],
        queryFn: () => systemFetcher<SystemHealth>(SYSTEM_ENDPOINTS.health),
    });
    return { data, isLoading, isError: !!error, error };
}

export function useOrchestratorState() {
    const queryClient = useQueryClient();
    const { data, error, isLoading } = useQuery<OrchestratorState>({
        queryKey: [SYSTEM_ENDPOINTS.orchestratorState],
        queryFn: () => systemFetcher<OrchestratorState>(SYSTEM_ENDPOINTS.orchestratorState),
        refetchInterval: 5_000,
    });

    const mutate = () => queryClient.invalidateQueries({ queryKey: [SYSTEM_ENDPOINTS.orchestratorState] });

    return { data, isLoading, isError: !!error, error, mutate };
}
