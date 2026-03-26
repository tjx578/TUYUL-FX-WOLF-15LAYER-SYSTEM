/**
 * @deprecated Use `AgentManagerEvents` from `@/components/agent-manager` instead. Sunset: 2026-06-01
 */
"use client";

import { useEffect, useRef } from "react";
import { AgentManagerEvents } from "@/components/agent-manager";
import type { EALog } from "@/types";
import type { AgentEvent } from "@/types/agent-manager";

interface Props {
    logs: EALog[] | undefined;
    isLoading?: boolean;
}

function _toAgentEvent(log: EALog): AgentEvent {
    return {
        id: log.id,
        agent_id: log.agent_id ?? "",
        event_type: log.level,
        severity: (log.level === "ERROR" ? "CRITICAL" : log.level === "WARNING" ? "WARNING" : "INFO") as AgentEvent["severity"],
        message: log.message,
        metadata: {},
        created_at: log.timestamp,
    };
}

/** @deprecated Use AgentManagerEvents from @/components/agent-manager instead. Sunset: 2026-06-01 */
export function AgentLogsPanel({ logs, isLoading }: Props) {
    const warnedRef = useRef(false);
    useEffect(() => {
        if (!warnedRef.current) {
            warnedRef.current = true;
            console.warn("[DEPRECATED] AgentLogsPanel: Use AgentManagerEvents from @/components/agent-manager instead");
        }
    }, []);

    return (
        <AgentManagerEvents
            events={(logs ?? []).map(_toAgentEvent)}
            isLoading={isLoading}
        />
    );
}
