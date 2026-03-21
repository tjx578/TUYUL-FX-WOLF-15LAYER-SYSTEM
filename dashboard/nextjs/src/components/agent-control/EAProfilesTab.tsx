/**
 * @deprecated Use `AgentManagerProfiles` from `@/components/agent-manager` instead. Sunset: 2026-06-01
 */
"use client";

import { useEffect, useRef } from "react";
import { AgentManagerProfiles } from "@/components/agent-manager";
import { useAgentManagerProfiles } from "@/lib/agent-manager-api";
import type { EAAgent } from "@/types";
import type { AgentItem } from "@/types/agent-manager";
import { AgentStatus, EAClass, EASubtype, ExecutionMode, ReporterMode } from "@/types/agent-manager";

interface Props {
    agents: EAAgent[];
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
    };
}

/** @deprecated Use AgentManagerProfiles from @/components/agent-manager instead. Sunset: 2026-06-01 */
export function EAProfilesTab({ agents }: Props) {
    const warnedRef = useRef(false);
    useEffect(() => {
        if (!warnedRef.current) {
            warnedRef.current = true;
            console.warn("[DEPRECATED] EAProfilesTab: Use AgentManagerProfiles from @/components/agent-manager instead");
        }
    }, []);

    const { data: profiles, isLoading } = useAgentManagerProfiles();

    return (
        <AgentManagerProfiles
            profiles={profiles}
            agents={agents.map(_toAgentItem)}
            isLoading={isLoading}
        />
    );
}
