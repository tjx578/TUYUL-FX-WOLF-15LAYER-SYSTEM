"use client";

// ============================================================
// TUYUL FX Wolf-15 — SignalComparePanel
// Side-by-side comparison of two L12Verdict signals
// Read-only research surface — no execution from here
// ============================================================

import { useRouter } from "next/navigation";
import type { L12Verdict } from "@/types";
import type { CompareSlot } from "@/hooks/useSignalExplorerState";

interface SignalComparePanelProps {
  slots: CompareSlot;
  onClear: () => void;
  onRemove: (symbol: string) => void;
}

const METRICS: {
  label: string;
  key: keyof L12Verdict | string;
  format?: (v: unknown) => string;
  colorize?: (v: unknown) => string;
}[] = [
  { label: "Verdict", key: "verdict", format: (v) => String(v ?? "—") },
  {
    label: "Confidence",
    key: "confidence",
    format: (v) => v != null ? `${Math.round((v as number) * 100)}%` : "—",
    colorize: (v) => {
      const n = (v as number) ?? 0;
      if (n >= 0.8) return "var(--green)";
      if (n >= 0.6) return "var(--yellow)";
      return "var(--red)";
    },
  },
  { label: "Direction", key: "direction", format: (v) => String(v ?? "—") },
  { label: "Entry", key: "entry_price", format: (v) => (v as number)?.toFixed(5) ?? "—" },
  { label: "Stop Loss", key: "stop_loss", format: (v) => (v as number)?.toFixed(5) ?? "—" },
  { label: "Take Profit", key: "take_profit_1", format: (v) => (v as number)?.toFixed(5) ?? "—" },
  {
    label: "R:R",
    key: "risk_reward_ratio",
    format: (v) => v != null ? `1:${(v as number).toFixed(2)}` : "—",
    colorize: (v) => ((v as number) ?? 0) >= 2 ? "var(--green)" : "var(--yellow)",
  },
  { label: "Session", key: "session", format: (v) => String(v ?? "—") },
  { label: "Wolf Score", key: "wolf", format: (v) => v != null ? `${(v as number).toFixed(0)}` : "—" },
  { label: "TII Score", key: "tii", format: (v) => v != null ? `${(v as number).toFixed(0)}` : "—" },
  { label: "FRPC Score", key: "frpc", format: (v) => v != null ? `${(v as number).toFixed(0)}` : "—" },
  { label: "Regime", key: "regime", format: (v) => String(v ?? "—") },
];

function getMetricValue(v: L12Verdict, key: string): unknown {
  if (key === "wolf") return v.scores?.wolf_score;
  if (key === "tii") return v.scores?.tii_score;
  if (key === "frpc") return v.scores?.frpc_score;
  if (key === "regime") return v.scores?.regime;
  return (v as unknown as Record<string, unknown>)[key];
}

function ScoreBar({ value, max = 100 }: { value: number; max?: number }) {
  const pct = Math.min((value / max) * 100, 100);
  const color = pct >= 70 ? "var(--green)" : pct >= 50 ? "var(--yellow)" : "var(--red)";
  return (
    <div style={{ marginTop: 3, height: 3, borderRadius: 2, background: "var(--bg-elevated)", overflow: "hidden" }}>
      <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 2 }} />
    </div>
  );
}

function GatesColumn({ verdict }: { verdict: L12Verdict }) {
  const passed = verdict.gates?.filter((g) => g.passed).length ?? 0;
  const total = verdict.gates?.length ?? 0;
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "var(--text-muted)", marginBottom: 6 }}>
        GATES — {passed}/{total}
      </div>
      {verdict.gates?.map((g) => (
        <div
          key={g.gate_id}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "4px 6px",
            borderRadius: 4,
            marginBottom: 3,
            background: g.passed ? "rgba(0,230,118,0.05)" : "rgba(255,61,87,0.05)",
            border: `1px solid ${g.passed ? "rgba(0,230,118,0.12)" : "rgba(255,61,87,0.12)"}`,
          }}
        >
          <span style={{ fontSize: 10, color: g.passed ? "var(--green)" : "var(--red)" }}>
            {g.passed ? "✓" : "✗"}
          </span>
          <span style={{ fontSize: 10, color: g.passed ? "var(--text-secondary)" : "var(--text-muted)", flex: 1 }}>
            {g.name || g.gate_id}
          </span>
          {g.message && (
            <span style={{ fontSize: 9, fontFamily: "var(--font-mono)", color: "var(--text-faint)" }}>
              {g.message}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

function VerdictColumn({ verdict, onRemove }: { verdict: L12Verdict; onRemove: () => void }) {
  const router = useRouter();
  const isExecutable = String(verdict.verdict).startsWith("EXECUTE");
  const dirColor = verdict.direction === "BUY" ? "var(--green)" : "var(--red)";

  return (
    <div
      style={{
        flex: 1,
        background: "var(--bg-elevated)",
        border: "1px solid var(--border-default)",
        borderRadius: "var(--radius-lg)",
        padding: "14px 16px",
        minWidth: 0,
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
        <span
          style={{
            fontSize: 16,
            fontWeight: 800,
            letterSpacing: "0.05em",
            color: "var(--text-primary)",
            fontFamily: "var(--font-display)",
          }}
        >
          {verdict.symbol}
        </span>
        {verdict.direction && (
          <span
            style={{
              fontSize: 10,
              fontWeight: 700,
              color: dirColor,
              background: verdict.direction === "BUY" ? "rgba(0,230,118,0.10)" : "rgba(255,61,87,0.10)",
              border: `1px solid ${dirColor}40`,
              borderRadius: "var(--radius-sm)",
              padding: "2px 7px",
              letterSpacing: "0.08em",
            }}
          >
            {verdict.direction}
          </span>
        )}
        <button
          onClick={onRemove}
          style={{
            marginLeft: "auto",
            background: "transparent",
            border: "1px solid var(--border-strong)",
            color: "var(--text-muted)",
            borderRadius: 4,
            padding: "2px 7px",
            fontSize: 10,
            cursor: "pointer",
          }}
        >
          Remove
        </button>
      </div>

      {/* Metric rows */}
      {METRICS.map(({ label, key, format, colorize }) => {
        const raw = getMetricValue(verdict, key);
        const formatted = format ? format(raw) : String(raw ?? "—");
        const color = colorize ? colorize(raw) : "var(--text-primary)";
        const isScore = ["wolf", "tii", "frpc"].includes(key);
        return (
          <div
            key={key}
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-start",
              padding: "5px 0",
              borderBottom: "1px solid var(--border-subtle)",
            }}
          >
            <span style={{ fontSize: 10, color: "var(--text-muted)", letterSpacing: "0.04em" }}>{label}</span>
            <div style={{ textAlign: "right" }}>
              <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color, fontWeight: 600 }}>
                {formatted}
              </span>
              {isScore && raw != null && <ScoreBar value={raw as number} />}
            </div>
          </div>
        );
      })}

      {/* Gates */}
      <GatesColumn verdict={verdict} />

      {/* Redirect to Signal Board CTA if executable */}
      {isExecutable && (
        <button
          onClick={() => router.push("/trades/signals")}
          style={{
            marginTop: 14,
            width: "100%",
            padding: "9px",
            borderRadius: "var(--radius-md)",
            background: "var(--accent)",
            border: "none",
            color: "#fff",
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: "0.07em",
            cursor: "pointer",
          }}
        >
          Execute on Signal Board
        </button>
      )}
    </div>
  );
}

function EmptySlot() {
  return (
    <div
      style={{
        flex: 1,
        background: "var(--bg-elevated)",
        border: "2px dashed var(--border-default)",
        borderRadius: "var(--radius-lg)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        minHeight: 200,
        minWidth: 0,
      }}
    >
      <span style={{ fontSize: 11, color: "var(--text-muted)", letterSpacing: "0.08em" }}>
        Click a signal card to compare
      </span>
    </div>
  );
}

export function SignalComparePanel({ slots, onClear, onRemove }: SignalComparePanelProps) {
  const hasAny = slots.a || slots.b;

  return (
    <div
      style={{
        background: "var(--bg-panel)",
        border: "1px solid var(--border-default)",
        borderRadius: "var(--radius-lg)",
        padding: "16px",
      }}
    >
      {/* Panel header */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
        <span
          style={{
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: "0.1em",
            color: "var(--text-secondary)",
          }}
        >
          COMPARE MODE
        </span>
        <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
          {[slots.a, slots.b].filter(Boolean).length}/2 selected
        </span>
        {hasAny && (
          <button
            onClick={onClear}
            style={{
              marginLeft: "auto",
              background: "transparent",
              border: "1px solid var(--border-strong)",
              color: "var(--text-muted)",
              borderRadius: "var(--radius-sm)",
              padding: "4px 10px",
              fontSize: 10,
              cursor: "pointer",
              letterSpacing: "0.06em",
            }}
          >
            Clear All
          </button>
        )}
      </div>

      {/* Columns */}
      <div style={{ display: "flex", gap: 12 }}>
        {slots.a ? (
          <VerdictColumn verdict={slots.a} onRemove={() => onRemove(slots.a!.symbol)} />
        ) : (
          <EmptySlot />
        )}
        {slots.b ? (
          <VerdictColumn verdict={slots.b} onRemove={() => onRemove(slots.b!.symbol)} />
        ) : (
          <EmptySlot />
        )}
      </div>
    </div>
  );
}
