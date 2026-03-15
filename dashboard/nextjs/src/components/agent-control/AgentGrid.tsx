"use client";

import type { EAAgent } from "@/types";
import { AgentCard } from "./AgentCard";

interface Props {
    agents: EAAgent[];
    selectedId: string | null;
    onSelect: (id: string) => void;
}

export function AgentGrid({ agents, selectedId, onSelect }: Props) {
    if (agents.length === 0) {
        return (
            <div
                style={{
                    padding: 24,
                    textAlign: "center",
                    color: "var(--text-muted)",
                    fontSize: 13,
                    border: "1px dashed var(--bg-border)",
                    borderRadius: 12,
                }}
            >
                No EA agents detected. Agents register automatically when an EA instance connects.
            </div>
        );
    }

    return (
        <div
            style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
                gap: 12,
            }}
        >
            {agents.map((agent) => (
                <AgentCard
                    key={agent.agent_id}
                    agent={agent}
                    selected={selectedId === agent.agent_id}
                    onSelect={onSelect}
                />
            ))}
        </div>
    );
}
