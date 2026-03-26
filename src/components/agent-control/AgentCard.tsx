/**
 * @deprecated Use `AgentManagerCard` from `@/components/agent-manager` instead. Sunset: 2026-06-01
 */
"use client";

import { useEffect, useRef } from "react";
import { AgentManagerCard } from "@/components/agent-manager";
import type { EAAgent } from "@/types";
import type { AgentItem } from "@/types/agent-manager";
import { AgentStatus, EAClass, EASubtype, ExecutionMode, ReporterMode } from "@/types/agent-manager";

interface Props {
    agent: EAAgent;
    selected: boolean;
    onSelect: (id: string) => void;
}

const _LEGACY_TO_AM_STATUS: Record<EAAgent["status"], AgentStatus> = {
    connected: AgentStatus.ONLINE,
    degraded: AgentStatus.WARNING,
    disconnected: AgentStatus.OFFLINE,
    cooldown: AgentStatus.QUARANTINED,
};

function _toAgentItem(agent: EAAgent): AgentItem {
    return {
        id: agent.agent_id,
        agent_name: agent.agent_id,
        ea_class: EAClass.PRIMARY,
        ea_subtype: EASubtype.STANDARD_REPORTER,
        execution_mode: ExecutionMode.LIVE,
        reporter_mode: ReporterMode.FULL,
        status: _LEGACY_TO_AM_STATUS[agent.status] ?? AgentStatus.OFFLINE,
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

/** @deprecated Use AgentManagerCard from @/components/agent-manager instead. Sunset: 2026-06-01 */
export function AgentCard({ agent, selected, onSelect }: Props) {
    const warnedRef = useRef(false);
    useEffect(() => {
        if (!warnedRef.current) {
            warnedRef.current = true;
            console.warn("[DEPRECATED] AgentCard: Use AgentManagerCard from @/components/agent-manager instead");
        }
    }, []);

    return (
        <AgentManagerCard
            agent={_toAgentItem(agent)}
            selected={selected}
            onSelect={onSelect}
        />
    );
}
