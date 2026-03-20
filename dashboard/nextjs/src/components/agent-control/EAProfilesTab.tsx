"use client";

import type { EAAgent } from "@/types";

interface Props {
    agents: EAAgent[];
}

export function EAProfilesTab({ agents }: Props) {
    const profiles = new Map<string, EAAgent[]>();
    for (const agent of agents) {
        const key = agent.profile || "default";
        const list = profiles.get(key) ?? [];
        list.push(agent);
        profiles.set(key, list);
    }

    if (profiles.size === 0) {
        return (
            <div style={{ padding: 16, color: "var(--text-muted)", fontSize: 12, textAlign: "center" }}>
                No profiles configured.
            </div>
        );
    }

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {Array.from(profiles.entries()).map(([profileName, profileAgents]) => (
                <div
                    key={profileName}
                    style={{
                        padding: 14,
                        borderRadius: 10,
                        border: "1px solid var(--bg-border)",
                        background: "var(--bg-card)",
                    }}
                >
                    <div
                        style={{
                            fontSize: 12,
                            fontWeight: 700,
                            letterSpacing: "0.06em",
                            color: "var(--text-primary)",
                            marginBottom: 8,
                            display: "flex",
                            alignItems: "center",
                            gap: 6,
                        }}
                    >
                        <span
                            style={{
                                width: 8,
                                height: 8,
                                borderRadius: "50%",
                                background: profileAgents.some((a) => a.healthy) ? "var(--green)" : "var(--red)",
                            }}
                        />
                        {profileName.toUpperCase()}
                        <span style={{ fontSize: 10, color: "var(--text-muted)", fontWeight: 400 }}>
                            ({profileAgents.length} agent{profileAgents.length !== 1 ? "s" : ""})
                        </span>
                    </div>

                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                        {profileAgents.map((agent) => (
                            <div
                                key={agent.agent_id}
                                style={{
                                    display: "flex",
                                    justifyContent: "space-between",
                                    alignItems: "center",
                                    fontSize: 11,
                                    padding: "4px 0",
                                    borderBottom: "1px solid var(--bg-border)",
                                }}
                            >
                                <span style={{ color: "var(--text-secondary)" }}>{agent.agent_id}</span>
                                <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                    <span style={{ color: "var(--text-muted)" }}>
                                        scope: {agent.scope}
                                    </span>
                                    <span
                                        style={{
                                            fontSize: 10,
                                            fontWeight: 600,
                                            color: agent.healthy ? "var(--green)" : "var(--red)",
                                        }}
                                    >
                                        {agent.status.toUpperCase()}
                                    </span>
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            ))}
        </div>
    );
}
