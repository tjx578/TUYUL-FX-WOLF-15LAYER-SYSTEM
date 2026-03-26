/**
 * @deprecated Use `AgentManagerGrid` from `@/components/agent-manager` instead. Sunset: 2026-06-01
 */
"use client";

import { useEffect, useRef } from "react";
import { AgentManagerGrid } from "@/components/agent-manager";
import type { EAAgent } from "@/types";
import type { AgentItem } from "@/types/agent-manager";
import { AgentStatus, EAClass, EASubtype, ExecutionMode, ReporterMode } from "@/types/agent-manager";

interface Props {
    agents: EAAgent[];
    selectedId: string | null;
    onSelect: (id: string) => void;
}

function _toAgentItem(agent: EAAgent): AgentItem {
    const statusMap: Record<EAAgent["status"], AgentStatus> = {
        connected: AgentStatus.ONLINE,
        degraded: AgentStatus.WARNING,
        disconnected: AgentStatus.OFFLINE,
        cooldown: AgentStatus.QUARANTINED,
    };
    return {
        id: agent.agent_id,
        agent_name: agent.agent_id,
        ea_class: EAClass.PRIMARY,
        ea_subtype: EASubtype.STANDARD_REPORTER,
        execution_mode: ExecutionMode.LIVE,
        reporter_mode: ReporterMode.FULL,
        status: statusMap[agent.status] ?? AgentStatus.OFFLINE,
        linked_account_id: agent.account_id || null,
        linked_profile_id: null,
        mt5_login: null,
        mt5_server: null,
        broker_name: null,
        strategy_profile: agent.profile,
        risk_multiplier: 1.0,
        news_lock_setting: "NONE",
        safe_mode: false,
        locked: false,
        lock_reason: null,
        locked_at: null,
        locked_by: null,
        notes: null,
        version: agent.version,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        runtime: {
            agent_id: agent.agent_id,
            last_heartbeat: agent.last_heartbeat || null,
            last_success: agent.last_success || null,
            last_failure: agent.last_failure || null,
            failure_reason: agent.failure_reason || null,
            trades_executed: agent.trades_executed,
            trades_failed: agent.trades_failed,
            uptime_seconds: agent.uptime_seconds,
            cpu_usage_pct: null,
            memory_mb: null,
            connection_latency_ms: null,
            updated_at: new Date().toISOString(),
        },
    };
}

/** @deprecated Use AgentManagerGrid from @/components/agent-manager instead. Sunset: 2026-06-01 */
export function AgentGrid({ agents, selectedId, onSelect }: Props) {
    const warnedRef = useRef(false);
    useEffect(() => {
        if (!warnedRef.current) {
            warnedRef.current = true;
            console.warn("[DEPRECATED] AgentGrid: Use AgentManagerGrid from @/components/agent-manager instead");
        }
    }, []);

    return (
        <AgentManagerGrid
            agents={agents.map(_toAgentItem)}
            selectedId={selectedId}
            onSelect={onSelect}
            filters={{}}
            onFiltersChange={() => undefined}
        />
    );
}
