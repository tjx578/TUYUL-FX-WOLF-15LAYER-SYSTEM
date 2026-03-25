"use client";

import type { AgentItem, AgentListFilters } from "@/types/agent-manager";
import { EAClass, AgentStatus } from "@/types/agent-manager";
import { AgentManagerCard } from "./AgentManagerCard";

interface Props {
  agents: AgentItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  filters: AgentListFilters;
  onFiltersChange: (filters: AgentListFilters) => void;
}

const EA_CLASS_OPTIONS: Array<{ label: string; value: EAClass | undefined }> = [
  { label: "ALL", value: undefined },
  { label: "PRIMARY", value: EAClass.PRIMARY },
  { label: "PORTFOLIO", value: EAClass.PORTFOLIO },
];

const STATUS_OPTIONS: Array<{ label: string; value: AgentStatus | undefined }> = [
  { label: "ALL", value: undefined },
  { label: "ONLINE", value: AgentStatus.ONLINE },
  { label: "WARNING", value: AgentStatus.WARNING },
  { label: "OFFLINE", value: AgentStatus.OFFLINE },
  { label: "QUARANTINED", value: AgentStatus.QUARANTINED },
  { label: "DISABLED", value: AgentStatus.DISABLED },
];

export function AgentManagerGrid({ agents, selectedId, onSelect, filters, onFiltersChange }: Props) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.08em", color: "var(--text-muted)", minWidth: 48 }}>CLASS</span>
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {EA_CLASS_OPTIONS.map((opt) => (
              <button
                key={opt.label}
                onClick={() => onFiltersChange({ ...filters, ea_class: opt.value })}
                style={{
                  fontSize: 10, fontWeight: 600, letterSpacing: "0.05em", padding: "2px 10px", borderRadius: 6,
                  border: filters.ea_class === opt.value ? "1px solid var(--cyan, #06b6d4)" : "1px solid var(--bg-border)",
                  background: filters.ea_class === opt.value ? "rgba(6,182,212,0.12)" : "transparent",
                  color: filters.ea_class === opt.value ? "var(--cyan, #06b6d4)" : "var(--text-muted)",
                  cursor: "pointer",
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.08em", color: "var(--text-muted)", minWidth: 48 }}>STATUS</span>
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {STATUS_OPTIONS.map((opt) => (
              <button
                key={opt.label}
                onClick={() => onFiltersChange({ ...filters, status: opt.value })}
                style={{
                  fontSize: 10, fontWeight: 600, letterSpacing: "0.05em", padding: "2px 10px", borderRadius: 6,
                  border: filters.status === opt.value ? "1px solid var(--cyan, #06b6d4)" : "1px solid var(--bg-border)",
                  background: filters.status === opt.value ? "rgba(6,182,212,0.12)" : "transparent",
                  color: filters.status === opt.value ? "var(--cyan, #06b6d4)" : "var(--text-muted)",
                  cursor: "pointer",
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {agents.length === 0 ? (
        <div style={{ padding: 24, textAlign: "center", color: "var(--text-muted)", fontSize: 13, border: "1px dashed var(--bg-border)", borderRadius: 12 }}>
          No agents found. Agents register automatically when an EA instance connects.
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 12 }}>
          {agents.map((agent) => (
            <AgentManagerCard key={agent.id} agent={agent} selected={selectedId === agent.id} onSelect={onSelect} />
          ))}
        </div>
      )}
    </div>
  );
}
