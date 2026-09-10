"use client";

import type { TradeStatus } from "@/types";

const STATUS_MAP: Record<string, { label: string; cls: string }> = {
  OPEN:      { label: "OPEN",      cls: "badge-green"  },
  PENDING:   { label: "PENDING",   cls: "badge-yellow" },
  INTENDED:  { label: "INTENDED",  cls: "badge-blue"   },
  CLOSED:    { label: "CLOSED",    cls: "badge-muted"  },
  CANCELLED: { label: "CANCELLED", cls: "badge-muted"  },
  SKIPPED:   { label: "SKIPPED",   cls: "badge-muted"  },
};

export function TradeStatusBadge({ status }: { status?: string }) {
  const cfg = STATUS_MAP[status ?? ""] ?? { label: status ?? "—", cls: "badge-muted" };
  return <span className={`badge ${cfg.cls}`}>{cfg.label}</span>;
}

export function DirectionBadge({ dir }: { dir?: string }) {
  if (!dir) return <span style={{ color: "var(--text-muted)" }}>—</span>;
  return (
    <span
      className="badge num"
      style={{
        background: dir === "BUY" ? "var(--green-glow)" : "var(--red-glow)",
        color:      dir === "BUY" ? "var(--green)"     : "var(--red)",
        border:     `1px solid ${dir === "BUY" ? "var(--border-success)" : "var(--border-danger)"}`,
        fontSize: 10,
        fontWeight: 800,
      }}
    >
      {dir}
    </span>
  );
}

export function PnlCell({ pnl, percent }: { pnl?: number; percent?: number }) {
  if (pnl === undefined || pnl === null)
    return <span style={{ color: "var(--text-muted)" }}>—</span>;
  const color = pnl >= 0 ? "var(--green)" : "var(--red)";
  return (
    <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 1 }}>
      <span className="num" style={{ color, fontWeight: 700, fontSize: 12 }}>
        {pnl >= 0 ? "+" : ""}{pnl.toFixed(2)}
      </span>
      {percent !== undefined && (
        <span className="num" style={{ color, fontSize: 9, opacity: 0.75 }}>
          {percent >= 0 ? "+" : ""}{percent.toFixed(2)}%
        </span>
      )}
    </span>
  );
}
