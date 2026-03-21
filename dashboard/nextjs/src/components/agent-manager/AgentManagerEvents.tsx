"use client";

import type { AgentEvent } from "@/types/agent-manager";

interface Props {
  events: AgentEvent[];
  isLoading?: boolean;
}

const SEVERITY_COLORS: Record<AgentEvent["severity"], string> = {
  INFO: "var(--cyan, #06b6d4)",
  WARNING: "var(--amber, #f59e0b)",
  CRITICAL: "var(--red)",
};

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString(undefined, { hour12: false });
  } catch {
    return iso;
  }
}

export function AgentManagerEvents({ events, isLoading }: Props) {
  if (isLoading) {
    return (
      <div style={{ padding: 12, color: "var(--text-muted)", fontSize: 11 }}>
        Loading events...
      </div>
    );
  }

  if (events.length === 0) {
    return (
      <div
        style={{ padding: 12, color: "var(--text-muted)", fontSize: 11, textAlign: "center" }}
      >
        No events recorded.
      </div>
    );
  }

  return (
    <div
      style={{
        maxHeight: 300,
        overflowY: "auto",
        display: "flex",
        flexDirection: "column",
        gap: 2,
        fontFamily: "var(--font-mono, monospace)",
        fontSize: 11,
      }}
    >
      {events.map((evt) => (
        <div
          key={evt.id}
          style={{
            display: "flex",
            gap: 8,
            padding: "4px 4px",
            borderBottom: "1px solid rgba(255,255,255,0.03)",
            lineHeight: 1.4,
            alignItems: "flex-start",
          }}
        >
          {/* Timestamp */}
          <span style={{ color: "var(--text-muted)", flexShrink: 0, minWidth: 64 }}>
            {formatTime(evt.created_at)}
          </span>

          {/* Severity Badge */}
          <span
            style={{
              color: SEVERITY_COLORS[evt.severity] ?? "var(--text-muted)",
              fontWeight: 700,
              flexShrink: 0,
              minWidth: 64,
              fontSize: 10,
              letterSpacing: "0.04em",
            }}
          >
            {evt.severity}
          </span>

          {/* Event Type */}
          <span
            style={{
              color: "var(--text-muted)",
              flexShrink: 0,
              minWidth: 80,
              fontSize: 10,
              fontStyle: "italic",
            }}
          >
            {evt.event_type}
          </span>

          {/* Message */}
          <span style={{ color: "var(--text-secondary)", wordBreak: "break-word", flex: 1 }}>
            {evt.message}
          </span>
        </div>
      ))}
    </div>
  );
}
