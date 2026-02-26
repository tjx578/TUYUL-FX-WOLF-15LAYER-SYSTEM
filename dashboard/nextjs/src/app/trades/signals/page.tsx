"use client";

// ============================================================
// TUYUL FX Wolf-15 — Signal Queue Page (/trades/signals)
// Flow: View EXECUTE verdicts → TAKE or SKIP
// ============================================================

import { useState } from "react";
import { useAllVerdicts, useAccounts, usePairs } from "@/lib/api";
import { VerdictCard } from "@/components/VerdictCard";
import { GateStatus } from "@/components/GateStatus";
import { TakeSignalForm } from "@/components/TakeSignalForm";
import type { L12Verdict } from "@/types";

export default function SignalQueuePage() {
  const { data: verdicts, isLoading, mutate } = useAllVerdicts();
  const { data: accounts } = useAccounts();
  const { data: pairs } = usePairs();

  const [selectedVerdict, setSelectedVerdict] = useState<L12Verdict | null>(null);
  const [filterMode, setFilterMode] = useState<"ALL" | "EXECUTE" | "HOLD">("ALL");
  const [selectedPair, setSelectedPair] = useState<string>("ALL");

  const allVerdicts = Object.values(verdicts ?? {});

  const filtered = allVerdicts.filter((v) => {
    const matchMode =
      filterMode === "ALL" ||
      (filterMode === "EXECUTE" && v.verdict.toString().startsWith("EXECUTE")) ||
      (filterMode === "HOLD" && v.verdict === "HOLD");
    const matchPair =
      selectedPair === "ALL" || v.symbol === selectedPair;
    return matchMode && matchPair;
  });

  const executeSignals = allVerdicts.filter((v) =>
    v.verdict.toString().startsWith("EXECUTE")
  );

  return (
    <div style={{ padding: "24px 28px", display: "flex", flexDirection: "column", gap: 20 }}>
      {/* ── Header ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div>
          <h1
            style={{
              fontSize: 20,
              fontWeight: 700,
              letterSpacing: "0.04em",
              color: "var(--text-primary)",
              margin: 0,
            }}
          >
            SIGNAL QUEUE
          </h1>
          <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
            TAKE or SKIP L12 execution signals
          </p>
        </div>

        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          {executeSignals.length > 0 && (
            <span className="badge badge-gold">
              {executeSignals.length} EXECUTE
            </span>
          )}
        </div>
      </div>

      {/* ── Filters ── */}
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        {(["ALL", "EXECUTE", "HOLD"] as const).map((m) => (
          <button
            key={m}
            className="btn btn-ghost"
            style={{
              fontSize: 11,
              padding: "5px 12px",
              opacity: filterMode === m ? 1 : 0.5,
              borderColor: filterMode === m ? "var(--accent)" : "var(--bg-border)",
              color: filterMode === m ? "var(--accent)" : "var(--text-muted)",
            }}
            onClick={() => setFilterMode(m)}
          >
            {m}
          </button>
        ))}

        <select
          value={selectedPair}
          onChange={(e) => setSelectedPair(e.target.value)}
          style={{ fontSize: 12, padding: "5px 10px", marginLeft: 8 }}
        >
          <option value="ALL">ALL PAIRS</option>
          {(pairs ?? []).map((p) => (
            <option key={p.symbol} value={p.symbol}>
              {p.symbol}
            </option>
          ))}
        </select>

        <button
          className="btn btn-ghost"
          style={{ marginLeft: "auto", fontSize: 11 }}
          onClick={() => mutate()}
        >
          ↻ REFRESH
        </button>
      </div>

      {/* ── Two-column layout: verdict list + detail ── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: 20, alignItems: "start" }}>
        {/* ── Left: verdict cards ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {isLoading && (
            <div style={{ fontSize: 12, color: "var(--text-muted)", padding: 16 }}>
              Loading signals...
            </div>
          )}

          {!isLoading && filtered.length === 0 && (
            <div
              style={{
                fontSize: 12,
                color: "var(--text-muted)",
                padding: "32px",
                textAlign: "center",
                background: "var(--bg-panel)",
                borderRadius: 8,
              }}
            >
              No signals match the current filter.
            </div>
          )}

          {filtered.map((v) => (
            <VerdictCard
              key={v.symbol}
              verdict={v}
              selected={selectedVerdict?.symbol === v.symbol}
              onTake={() => setSelectedVerdict(v)}
              onSkip={() => setSelectedVerdict(v)}
            />
          ))}
        </div>

        {/* ── Right: detail panel ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14, position: "sticky", top: 24 }}>
          {selectedVerdict ? (
            <>
              {/* Gate check */}
              {selectedVerdict.gates?.length > 0 && (
                <div className="card">
                  <GateStatus gates={selectedVerdict.gates} />
                </div>
              )}

              {/* Take/Skip form */}
              {accounts && (
                <TakeSignalForm
                  verdict={selectedVerdict}
                  accounts={accounts}
                  onDone={() => {
                    setSelectedVerdict(null);
                    mutate();
                  }}
                  onCancel={() => setSelectedVerdict(null)}
                />
              )}
            </>
          ) : (
            <div
              style={{
                padding: 24,
                textAlign: "center",
                fontSize: 12,
                color: "var(--text-muted)",
                background: "var(--bg-panel)",
                borderRadius: 8,
                border: "1px dashed var(--bg-border)",
              }}
            >
              Select a signal to view gates &amp; take/skip options
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
