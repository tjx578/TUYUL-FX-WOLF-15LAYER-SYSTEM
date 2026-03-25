"use client";

import { useState } from "react";
import type { AgentAuditLog } from "@/types/agent-manager";
import { formatDateTime } from "@/lib/formatters";

interface Props {
  logs: AgentAuditLog[];
  isLoading?: boolean;
}

function JsonPreview({ value }: { value: Record<string, unknown> | null }) {
  if (!value || Object.keys(value).length === 0) return <span style={{ color: "var(--text-muted)" }}>—</span>;
  return (
    <pre style={{ margin: 0, padding: "4px 8px", background: "rgba(0,0,0,0.2)", borderRadius: 4, fontSize: 10, color: "var(--text-secondary)", overflowX: "auto", maxHeight: 80, overflowY: "auto" }}>
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function AgentManagerAudit({ logs, isLoading }: Props) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  if (isLoading) {
    return <div style={{ padding: 12, color: "var(--text-muted)", fontSize: 11 }}>Loading audit log...</div>;
  }

  if (logs.length === 0) {
    return <div style={{ padding: 12, color: "var(--text-muted)", fontSize: 11, textAlign: "center" }}>No audit entries.</div>;
  }

  return (
    <div style={{ maxHeight: 360, overflowY: "auto", display: "flex", flexDirection: "column", gap: 2, fontFamily: "var(--font-mono, monospace)", fontSize: 11 }}>
      {logs.map((log) => {
        const isExpanded = expandedId === log.id;
        return (
          <div key={log.id} style={{ borderBottom: "1px solid rgba(255,255,255,0.04)", padding: "4px 0" }}>
            <div
              style={{ display: "flex", gap: 8, alignItems: "center", cursor: "pointer", padding: "2px 4px" }}
              onClick={() => setExpandedId(isExpanded ? null : log.id)}
            >
              <span style={{ color: "var(--text-muted)", flexShrink: 0, minWidth: 100 }}>{formatDateTime(log.created_at)}</span>
              <span style={{ color: "var(--cyan, #06b6d4)", fontWeight: 700, flexShrink: 0, letterSpacing: "0.04em" }}>{log.action}</span>
              <span style={{ color: "var(--text-muted)", flexShrink: 0 }}>by {log.performed_by}</span>
              <span style={{ marginLeft: "auto", color: "var(--text-muted)", fontSize: 10 }}>{isExpanded ? "▲" : "▼"}</span>
            </div>
            {isExpanded && (
              <div style={{ padding: "6px 4px 4px", display: "flex", flexDirection: "column", gap: 6 }}>
                {Object.keys(log.details).length > 0 && (
                  <div>
                    <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.08em", color: "var(--text-muted)" }}>DETAILS</span>
                    <JsonPreview value={log.details} />
                  </div>
                )}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                  <div>
                    <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.08em", color: "var(--text-muted)" }}>BEFORE</span>
                    <JsonPreview value={log.previous_state} />
                  </div>
                  <div>
                    <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.08em", color: "var(--text-muted)" }}>AFTER</span>
                    <JsonPreview value={log.new_state} />
                  </div>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
