"use client";

import { useMemo, useCallback, useState } from "react";
import {
    useEAStatus,
    useEAAgents,
    useEALogs,
    restartEA,
    setEASafeMode,
} from "@/lib/api";
import { useAgentStore } from "@/store/useAgentStore";
import type { EAAgent, EAStatus, EALog, AgentFailure } from "@/types";

export interface AgentHealthSummary {
    totalAgents: number;
    connectedAgents: number;
    disconnectedAgents: number;
    healthPercent: number;
    overallStatus: "healthy" | "degraded" | "critical" | "offline";
}

export interface AgentControlState {
    // Data
    status: EAStatus | undefined;
    agents: EAAgent[];
    logs: EALog[] | undefined;
    selectedAgent: EAAgent | null;

    // Derived
    agentHealthSummary: AgentHealthSummary;
    recentFailures: AgentFailure[];
    cooldownState: { active: boolean };

    // Loading
    isLoading: boolean;

    // UI state
    selectedAgentId: string | null;
    activeTab: "overview" | "profiles" | "logs";
    setSelectedAgent: (id: string | null) => void;
    setActiveTab: (tab: "overview" | "profiles" | "logs") => void;

    // Mutations
    handleRestart: () => Promise<{ success: boolean; error?: string }>;
    handleSetSafeMode: (
        enabled: boolean,
        reason: string
    ) => Promise<{ success: boolean; error?: string }>;

    // Refetch
    refreshAll: () => void;
}

export function useAgentControlState(): AgentControlState {
    const { data: status, isLoading: statusLoading, mutate: mutateStatus } = useEAStatus();
    const { data: agents, isLoading: agentsLoading, mutate: mutateAgents } = useEAAgents();
    const selectedAgentId = useAgentStore((s) => s.selectedAgentId);
    const { data: logs, mutate: mutateLogs } = useEALogs(selectedAgentId ?? undefined);
    const activeTab = useAgentStore((s) => s.activeTab);
    const setSelectedAgent = useAgentStore((s) => s.setSelectedAgent);
    const setActiveTab = useAgentStore((s) => s.setActiveTab);

    const selectedAgent = useMemo(
        () => agents.find((a) => a.agent_id === selectedAgentId) ?? null,
        [agents, selectedAgentId]
    );

    const agentHealthSummary = useMemo<AgentHealthSummary>(() => {
        const total = agents.length;
        const connected = agents.filter((a) => a.healthy).length;
        const disconnected = total - connected;
        const healthPercent = total > 0 ? Math.round((connected / total) * 100) : 0;

        let overallStatus: AgentHealthSummary["overallStatus"] = "healthy";
        if (total === 0 || !status?.running) overallStatus = "offline";
        else if (connected === 0) overallStatus = "critical";
        else if (disconnected > 0) overallStatus = "degraded";

        return { totalAgents: total, connectedAgents: connected, disconnectedAgents: disconnected, healthPercent, overallStatus };
    }, [agents, status]);

    const recentFailures = useMemo<AgentFailure[]>(
        () => status?.recent_failures ?? [],
        [status]
    );

    const cooldownState = useMemo(
        () => ({ active: status?.cooldown_active ?? false }),
        [status]
    );

    const refreshAll = useCallback(() => {
        mutateStatus();
        mutateAgents();
        mutateLogs();
    }, [mutateStatus, mutateAgents, mutateLogs]);

    const handleRestart = useCallback(async () => {
        try {
            await restartEA();
            refreshAll();
            return { success: true };
        } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : "Restart failed";
            return { success: false, error: msg };
        }
    }, [refreshAll]);

    const handleSetSafeMode = useCallback(
        async (enabled: boolean, reason: string) => {
            try {
                await setEASafeMode(enabled, reason);
                refreshAll();
                return { success: true };
            } catch (err: unknown) {
                const msg = err instanceof Error ? err.message : "Safe mode toggle failed";
                return { success: false, error: msg };
            }
        },
        [refreshAll]
    );

    return {
        status,
        agents,
        logs,
        selectedAgent,
        agentHealthSummary,
        recentFailures,
        cooldownState,
        isLoading: statusLoading || agentsLoading,
        selectedAgentId,
        activeTab,
        setSelectedAgent,
        setActiveTab,
        handleRestart,
        handleSetSafeMode,
        refreshAll,
    };
}
