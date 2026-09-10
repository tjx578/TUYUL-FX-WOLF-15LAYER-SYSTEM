"use client";

// ============================================================
// TUYUL FX Wolf-15 — SignalInspectorHeader
// Header row of the Signal Explorer showing context breadcrumb,
// session/regime, and "Go to Signal Board" CTA
// ============================================================

import { useRouter } from "next/navigation";
import type { ContextSnapshot } from "@/types";

interface SignalInspectorHeaderProps {
  context: ContextSnapshot | undefined;
  totalCount: number;
  filteredCount: number;
  compareMode: boolean;
  compareCount: number;
}

export function SignalInspectorHeader({
  context,
  totalCount,
  filteredCount,
  compareMode,
  compareCount,
}: SignalInspectorHeaderProps) {
  const router = useRouter();

  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: 16, flexWrap: "wrap" }}>
      {/* Title block */}
      <div style={{ flex: 1, minWidth: 200 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
          <span
            style={{
              fontSize: 20,
              fontWeight: 800,
              letterSpacing: "0.06em",
              fontFamily: "var(--font-display)",
              color: "var(--text-primary)",
            }}
          >
            SIGNAL EXPLORER
          </span>
          <span
            style={{
              padding: "2px 8px",
              borderRadius: "var(--radius-sm)",
              background: "rgba(26,110,255,0.12)",
              border: "1px solid rgba(26,110,255,0.3)",
              fontSize: 9,
              fontFamily: "var(--font-mono)",
              color: "var(--accent)",
              letterSpacing: "0.1em",
            }}
          >
            RESEARCH
          </span>
          {compareMode && (
            <span
              style={{
                padding: "2px 8px",
                borderRadius: "var(--radius-sm)",
                background: "rgba(0,212,255,0.12)",
                border: "1px solid rgba(0,212,255,0.3)",
                fontSize: 9,
                fontFamily: "var(--font-mono)",
                color: "var(--cyan)",
                letterSpacing: "0.1em",
              }}
            >
              COMPARE {compareCount}/2
            </span>
          )}
        </div>
        <div
          style={{
            fontSize: 11,
            color: "var(--text-muted)",
            fontFamily: "var(--font-body)",
          }}
        >
          Inspect, filter and compare L12 verdicts. For execution, use Signal Board.
        </div>
      </div>

      {/* Context chips */}
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        {context?.session && (
          <div
            style={{
              padding: "6px 12px",
              borderRadius: "var(--radius-md)",
              background: "var(--bg-card)",
              border: "1px solid var(--border-default)",
              display: "flex",
              flexDirection: "column",
              gap: 1,
            }}
          >
            <span style={{ fontSize: 8, letterSpacing: "0.1em", color: "var(--text-muted)" }}>SESSION</span>
            <span style={{ fontSize: 12, fontWeight: 700, color: "var(--cyan)", letterSpacing: "0.05em" }}>
              {context.session}
            </span>
          </div>
        )}
        {context?.regime && (
          <div
            style={{
              padding: "6px 12px",
              borderRadius: "var(--radius-md)",
              background: "var(--bg-card)",
              border: "1px solid var(--border-default)",
              display: "flex",
              flexDirection: "column",
              gap: 1,
            }}
          >
            <span style={{ fontSize: 8, letterSpacing: "0.1em", color: "var(--text-muted)" }}>REGIME</span>
            <span style={{ fontSize: 12, fontWeight: 700, color: "var(--text-primary)", letterSpacing: "0.05em" }}>
              {context.regime}
            </span>
          </div>
        )}
        <div
          style={{
            padding: "6px 12px",
            borderRadius: "var(--radius-md)",
            background: "var(--bg-card)",
            border: "1px solid var(--border-default)",
            display: "flex",
            flexDirection: "column",
            gap: 1,
          }}
        >
          <span style={{ fontSize: 8, letterSpacing: "0.1em", color: "var(--text-muted)" }}>SIGNALS</span>
          <span style={{ fontSize: 12, fontWeight: 700, color: "var(--text-primary)", letterSpacing: "0.05em" }}>
            {filteredCount}
            <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>/{totalCount}</span>
          </span>
        </div>

        {/* CTA: Go to Signal Board */}
        <button
          onClick={() => router.push("/trades/signals")}
          style={{
            padding: "8px 14px",
            borderRadius: "var(--radius-md)",
            background: "var(--accent)",
            border: "none",
            color: "#fff",
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: "0.07em",
            cursor: "pointer",
            whiteSpace: "nowrap",
          }}
        >
          Signal Board
        </button>
      </div>
    </div>
  );
}
