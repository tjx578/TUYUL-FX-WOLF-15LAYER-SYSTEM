"use client";

// ============================================================
// TUYUL FX Wolf-15 — Signals Page (/trades/signals)
// Shows all L12 verdicts with gate details and take/skip actions
// ============================================================

import { useAllVerdicts, useAccounts } from "@/lib/api";
import { VerdictCard } from "@/components/VerdictCard";
import { TakeSignalForm } from "@/components/TakeSignalForm";
import { useState } from "react";
import type { L12Verdict } from "@/types";

export default function SignalsPage() {
  const { data: verdicts, isLoading } = useAllVerdicts();
  const { data: accounts } = useAccounts();
  const [selected, setSelected] = useState<L12Verdict | null>(null);

  if (isLoading) {
    return (
      <div style={{ padding: "2rem" }}>
        <h1 style={{ color: "var(--accent)", fontFamily: "var(--font-display)", fontSize: "1.5rem", marginBottom: "1rem" }}>
          ◈ SIGNALS
        </h1>
        <p style={{ color: "var(--text-muted)" }}>Loading verdicts…</p>
      </div>
    );
  }

  const list = verdicts ? Object.values(verdicts) : [];

  return (
    <div style={{ padding: "2rem" }}>
      <h1 style={{ color: "var(--accent)", fontFamily: "var(--font-display)", fontSize: "1.5rem", marginBottom: "1.5rem" }}>
        ◈ ALL SIGNALS ({list.length})
      </h1>

      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
        gap: "1rem",
      }}>
        {list.map((v) => (
          <VerdictCard
            key={v.symbol}
            verdict={v}
            onTake={() => setSelected(v)}
            onSkip={() => {}}
            selected={selected?.symbol === v.symbol}
          />
        ))}
      </div>

      {list.length === 0 && (
        <p style={{ color: "var(--text-muted)", textAlign: "center", marginTop: "3rem" }}>
          No active signals
        </p>
      )}

      {selected && (
        <TakeSignalForm
          verdict={selected}
          accounts={accounts ?? []}
          onDone={() => setSelected(null)}
          onCancel={() => setSelected(null)}
        />
      )}
    </div>
  );
}
