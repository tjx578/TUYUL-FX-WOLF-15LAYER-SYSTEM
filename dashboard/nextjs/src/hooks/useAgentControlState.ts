"use client";

/**
 * @deprecated Use `useAgentManagerState` from `@/hooks/useAgentManagerState` instead. Sunset: 2026-06-01
 */

import { useMemo, useCallback, useEffect, useRef } from "react";
import { useAgentManagerState } from "@/hooks/useAgentManagerState";
import { AgentStatus as AgentStatusEnum } from "@/types/agent-manager";
import { useAgentStore } from "@/store/useAgentStore";
import type { EAAgent, EAStatus, EALog, AgentFailure } from "@/types";
import type { AgentItem, AgentEvent } from "@/types/agent-manager";

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

// ── Mapping helpers ───────────────────────────────────────────

const _STATUS_MAP: Record<AgentStatusEnum, EAAgent["status"]> = {
    [AgentStatusEnum.ONLINE]: "connected",
    [AgentStatusEnum.WARNING]: "degraded",
    [AgentStatusEnum.OFFLINE]: "disconnected",
    [AgentStatusEnum.QUARANTINED]: "cooldown",
    [AgentStatusEnum.DISABLED]: "disconnected",
};

function _mapAgent(a: AgentItem): EAAgent {
    const legacy = _STATUS_MAP[a.status] ?? "disconnected";
    return {
        agent_id: a.id,
        account_id: a.linked_account_id ?? "",
        profile: a.strategy_profile ?? "default",
        status: legacy,
        healthy: legacy === "connected",
        last_heartbeat: a.runtime?.last_heartbeat ?? "",
        last_success: a.runtime?.last_success ?? "",
        last_failure: a.runtime?.last_failure ?? "",
        failure_reason: a.runtime?.failure_reason ?? "",
        trades_executed: a.runtime?.trades_executed ?? 0,
        trades_failed: a.runtime?.trades_failed ?? 0,
        uptime_seconds: a.runtime?.uptime_seconds ?? 0,
        version: a.version ?? "unknown",
        scope: a.ea_class.toLowerCase(),
    };
}

function _mapEvent(ev: AgentEvent): EALog {
    return {
        id: ev.id,
        timestamp: ev.created_at,
        level: ev.severity,
        message: ev.message,
        agent_id: ev.agent_id,
    };
}

/**
 * @deprecated Use `useAgentManagerState` from `@/hooks/useAgentManagerState` instead. Sunset: 2026-06-01
 */
export function useAgentControlState(): AgentControlState {
    const warnedRef = useRef(false);
    useEffect(() => {
        if (!warnedRef.current) {
            warnedRef.current = true;
            console.warn("[DEPRECATED] useAgentControlState: Use useAgentManagerState instead");
        }
    }, []);

    const {
        agents,
        events,
        summary,
        isLoading,
        selectedAgentId: amSelectedId,
        setSelectedAgentId,
        activeTab: amActiveTab,
        setActiveTab: amSetActiveTab,
        handleLock,
        handleUnlock,
        handleToggleSafeMode,
        refreshAll,
    } = useAgentManagerState();

    // Bridge to legacy AgentStore for components that read from it directly
    const storeSelectedAgentId = useAgentStore((s) => s.selectedAgentId);
    const storeSetSelectedAgent = useAgentStore((s) => s.setSelectedAgent);
    const storeActiveTab = useAgentStore((s) => s.activeTab) as "overview" | "profiles" | "logs";
    const storeSetActiveTab = useAgentStore((s) => s.setActiveTab);

    // Derived: map new agents to legacy format
    const legacyAgents = useMemo(() => agents.map(_mapAgent), [agents]);

    // Derived: map events to legacy logs
    const legacyLogs = useMemo(() => events.map(_mapEvent), [events]);

    // Derived: selected agent in legacy format
    const selectedAgentId = storeSelectedAgentId ?? amSelectedId;
    const selectedAgent = useMemo(
        () => legacyAgents.find((a) => a.agent_id === selectedAgentId) ?? null,
        [legacyAgents, selectedAgentId]
    );

    // Derived: build legacy EAStatus from summary
    const status = useMemo<EAStatus>(() => ({
        healthy: summary.online > 0,
        running: summary.online > 0,
        engine_state: "IDLE",
        queue_depth: 0,
        queue_max: 200,
        safe_mode: agents.some((a) => a.safe_mode),
        agents_total: summary.total,
        agents_connected: summary.online,
        total_failures: agents.reduce((sum, a) => sum + (a.runtime?.trades_failed ?? 0), 0),
        recent_failures: [],
        cooldown_active: agents.some((a) => a.locked),
        updated_at: new Date().toISOString(),
    }), [summary, agents]);

    const agentHealthSummary = useMemo<AgentHealthSummary>(() => {
        const total = summary.total;
        const connected = summary.online;
        const disconnected = total - connected;
        const healthPercent = summary.healthPercent;
        let overallStatus: AgentHealthSummary["overallStatus"] = "healthy";
        if (total === 0) overallStatus = "offline";
        else if (connected === 0) overallStatus = "critical";
        else if (disconnected > 0) overallStatus = "degraded";
        return { totalAgents: total, connectedAgents: connected, disconnectedAgents: disconnected, healthPercent, overallStatus };
    }, [summary]);

    const recentFailures = useMemo<AgentFailure[]>(() => [], []);

    const cooldownState = useMemo(() => ({ active: agents.some((a) => a.locked) }), [agents]);

    const handleRestart = useCallback(async () => {
        const results = await Promise.allSettled(
            agents
                .filter((a) => a.status === AgentStatusEnum.ONLINE)
                .map(async (a) => {
                    await handleLock(a.id, { reason: "MANUAL_RESTART" });
                    await handleUnlock(a.id);
                })
        );
        const failed = results.filter((r): r is PromiseRejectedResult => r.status === "rejected");
        if (failed.length > 0) {
            const msg = failed.map((r) => String(r.reason)).join("; ");
            return { success: false, error: msg || "Restart failed" };
        }
        refreshAll();
        return { success: true };
    }, [agents, handleLock, handleUnlock, refreshAll]);

    const handleSetSafeMode = useCallback(async (enabled: boolean, _reason: string) => {
        const results = await Promise.allSettled(
            agents.map((a) => handleToggleSafeMode(a.id, !enabled))
        );
        const failed = results.filter((r): r is PromiseRejectedResult => r.status === "rejected");
        if (failed.length > 0) {
            const msg = failed.map((r) => String(r.reason)).join("; ");
            return { success: false, error: msg || "Safe mode toggle failed" };
        }
        refreshAll();
        return { success: true };
    }, [agents, handleToggleSafeMode, refreshAll]);

    // Bridged setters — sync both stores
    const setSelectedAgent = useCallback((id: string | null) => {
        storeSetSelectedAgent(id);
        setSelectedAgentId(id);
    }, [storeSetSelectedAgent, setSelectedAgentId]);

    const setActiveTab = useCallback((tab: "overview" | "profiles" | "logs") => {
        storeSetActiveTab(tab);
        // Map legacy tabs to new AM tabs where possible
        if (tab === "overview" || tab === "logs") amSetActiveTab("agents");
        if (tab === "profiles") amSetActiveTab("profiles");
    }, [storeSetActiveTab, amSetActiveTab]);

    return {
        status,
        agents: legacyAgents,
        logs: legacyLogs,
        selectedAgent,
        agentHealthSummary,
        recentFailures,
        cooldownState,
        isLoading,
        selectedAgentId,
        activeTab: storeActiveTab,
        setSelectedAgent,
        setActiveTab,
        handleRestart,
        handleSetSafeMode,
        refreshAll,
    };
}
