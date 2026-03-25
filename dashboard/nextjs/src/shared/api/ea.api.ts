import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { EALog, EAStatus, EAAgent } from "@/types";
import {
    useAgentManagerList,
    useAgentManagerEvents,
    lockAgent,
    unlockAgent,
    updateAgent,
} from "@/lib/agent-manager-api";
import { AgentStatus as AgentStatusEnum } from "@/types/agent-manager";
import type { AgentItem, AgentEvent } from "@/types/agent-manager";
import { apiMutate, API_ENDPOINTS } from "@/shared/api/client";

/** Map AgentItem to legacy EAAgent shape. */
function _agentItemToLegacy(a: AgentItem): EAAgent {
    const statusMap: Record<AgentStatusEnum, EAAgent["status"]> = {
        [AgentStatusEnum.ONLINE]: "connected",
        [AgentStatusEnum.WARNING]: "degraded",
        [AgentStatusEnum.OFFLINE]: "disconnected",
        [AgentStatusEnum.QUARANTINED]: "cooldown",
        [AgentStatusEnum.DISABLED]: "disconnected",
    };
    const legacyStatus = statusMap[a.status] ?? "disconnected";
    const runtime = a.runtime;
    return {
        agent_id: a.id,
        account_id: a.linked_account_id ?? "",
        profile: a.strategy_profile ?? "default",
        status: legacyStatus,
        healthy: legacyStatus === "connected",
        last_heartbeat: runtime?.last_heartbeat ?? "",
        last_success: runtime?.last_success ?? "",
        last_failure: runtime?.last_failure ?? "",
        failure_reason: runtime?.failure_reason ?? "",
        trades_executed: runtime?.trades_executed ?? 0,
        trades_failed: runtime?.trades_failed ?? 0,
        uptime_seconds: runtime?.uptime_seconds ?? 0,
        version: a.version ?? "unknown",
        scope: a.ea_class.toLowerCase(),
    };
}

/** Map AgentEvent to legacy EALog shape. */
function _agentEventToLog(ev: AgentEvent): EALog {
    return {
        id: ev.id,
        timestamp: ev.created_at,
        level: ev.severity,
        message: ev.message,
        agent_id: ev.agent_id,
    };
}

/**
 * @deprecated Use `useAgentManagerList` from `@/lib/agent-manager-api` instead. Sunset: 2026-06-01
 */
export function useEAStatus() {
    const { data: agents, isLoading, isError, error, mutate } = useAgentManagerList();
    const data: EAStatus | undefined = agents.length > 0 || !isLoading
        ? {
            healthy: agents.some((a) => a.status === AgentStatusEnum.ONLINE),
            running: agents.some((a) => a.status === AgentStatusEnum.ONLINE),
            engine_state: "IDLE",
            queue_depth: 0,
            queue_max: 200,
            safe_mode: agents.some((a) => a.safe_mode),
            agents_total: agents.length,
            agents_connected: agents.filter((a) => a.status === AgentStatusEnum.ONLINE).length,
            total_failures: agents.reduce((sum, a) => sum + (a.runtime?.trades_failed ?? 0), 0),
            recent_failures: [],
            cooldown_active: agents.some((a) => a.locked),
            updated_at: new Date().toISOString(),
        }
        : undefined;
    return { data, isLoading, isError, error, mutate };
}

/**
 * @deprecated Use `useAgentManagerEvents` from `@/lib/agent-manager-api` instead. Sunset: 2026-06-01
 */
export function useEALogs(agentId?: string) {
    const { data: events, isLoading, isError, error, mutate } = useAgentManagerEvents(agentId ?? null);
    const data: EALog[] | undefined = events.map(_agentEventToLog);
    return { data, isLoading, isError, error, mutate };
}

/**
 * @deprecated Use `useAgentManagerList` from `@/lib/agent-manager-api` instead. Sunset: 2026-06-01
 */
export function useEAAgents() {
    const { data: agents, isLoading, isError, error, mutate } = useAgentManagerList();
    return { data: agents.map(_agentItemToLegacy), isLoading, isError, error, mutate };
}

/**
 * Imperatively POST to `/api/v1/ea/ping` to verify EA → backend connectivity.
 */
export async function eaPing(
    agentId: string,
    eaVersion: string = "unknown",
    eaClass: string = "PRIMARY",
): Promise<{ status: string; server_time: string; agent_status: string }> {
    return apiMutate(API_ENDPOINTS.eaPing, {
        agent_id: agentId,
        ea_version: eaVersion,
        ea_class: eaClass,
    });
}

/**
 * SWR hook that periodically pings `/api/v1/ea/ping` to surface EA connectivity
 * status on the dashboard.
 */
export function useEAPing(agentId: string | null, refreshIntervalMs = 60_000) {
    const queryClient = useQueryClient();
    const key = agentId ? ["eaPing", agentId] : null;

    const { data, error, isLoading } = useQuery<{
        status: string;
        server_time: string;
        agent_status: string;
    }>({
        queryKey: key ?? ["eaPing", "__disabled__"],
        queryFn: () => eaPing(agentId!),
        enabled: !!agentId,
        refetchInterval: refreshIntervalMs,
    });

    const mutate = () =>
        queryClient.invalidateQueries({ queryKey: key ?? ["eaPing", "__disabled__"] });

    return {
        data,
        isLoading,
        isError: !!error,
        error,
        mutate,
        isOnline: data?.status === "ok",
    };
}

/**
 * @deprecated Use `lockAgent`/`unlockAgent` from `@/lib/agent-manager-api` instead. Sunset: 2026-06-01
 */
export async function restartEA(): Promise<void> {
    try {
        const res = await fetch("/api/v1/agent-manager/agents", { credentials: "include" });
        if (res.ok) {
            const payload = await res.json();
            const agents: AgentItem[] = Array.isArray(payload) ? payload : (payload.agents ?? []);
            for (const agent of agents) {
                if (agent.status === AgentStatusEnum.ONLINE) {
                    await lockAgent(agent.id, { reason: "MANUAL_RESTART", locked_by: "user:dashboard" });
                    await unlockAgent(agent.id);
                }
            }
            return;
        }
    } catch {
        // fall through to legacy
    }
    await apiMutate(API_ENDPOINTS.eaRestart, { reason: "MANUAL_RESTART" });
}

/**
 * @deprecated Use `updateAgent` from `@/lib/agent-manager-api` instead. Sunset: 2026-06-01
 */
export async function setEASafeMode(enabled: boolean, reason: string): Promise<void> {
    try {
        const res = await fetch("/api/v1/agent-manager/agents", { credentials: "include" });
        if (res.ok) {
            const payload = await res.json();
            const agents: AgentItem[] = Array.isArray(payload) ? payload : (payload.agents ?? []);
            for (const agent of agents) {
                await updateAgent(agent.id, { safe_mode: enabled });
            }
            return;
        }
    } catch {
        // fall through to legacy
    }
    await apiMutate(API_ENDPOINTS.eaSafeMode, { enabled, reason });
}
