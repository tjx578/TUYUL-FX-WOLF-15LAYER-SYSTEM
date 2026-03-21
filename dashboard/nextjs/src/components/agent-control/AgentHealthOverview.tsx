/**
 * @deprecated Use `AgentManagerSummary` from `@/components/agent-manager` instead. Sunset: 2026-06-01
 */
"use client";

import { useEffect, useRef } from "react";
import { AgentManagerSummary } from "@/components/agent-manager";
import type { AgentHealthSummary } from "@/hooks/useAgentControlState";
import type { AgentManagerSummary as AgentManagerSummaryType } from "@/hooks/useAgentManagerState";

interface Props {
    summary: AgentHealthSummary;
    safeMode: boolean;
    queueDepth: number;
    queueMax: number;
}

function _toManagerSummary(summary: AgentHealthSummary): AgentManagerSummaryType {
    return {
        total: summary.totalAgents,
        online: summary.connectedAgents,
        warning: 0,
        offline: summary.disconnectedAgents,
        quarantined: 0,
        disabled: 0,
        locked: 0,
        healthPercent: summary.healthPercent,
    };
}

/** @deprecated Use AgentManagerSummary from @/components/agent-manager instead. Sunset: 2026-06-01 */
export function AgentHealthOverview({ summary, safeMode, queueDepth, queueMax }: Props) {
    const warnedRef = useRef(false);
    useEffect(() => {
        if (!warnedRef.current) {
            warnedRef.current = true;
            console.warn("[DEPRECATED] AgentHealthOverview: Use AgentManagerSummary from @/components/agent-manager instead");
        }
    }, []);

    return <AgentManagerSummary summary={_toManagerSummary(summary)} />;
}
