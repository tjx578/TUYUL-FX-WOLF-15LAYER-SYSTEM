"use client";

import { useMemo, useState } from "react";
import { VerdictCard } from "@/components/VerdictCard";
import { TakeSignalForm } from "@/components/TakeSignalForm";
import { useAllVerdicts, useAccounts } from "@/lib/api";
import type { L12Verdict } from "@/types";

type FilterMode = "ALL" | "EXECUTE" | "NON_EXECUTE";

export default function SignalsPage() {
  const { data: verdictMap, isLoading } = useAllVerdicts();
  const { data: accounts } = useAccounts();

  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<FilterMode>("ALL");
  const [selected, setSelected] = useState<L12Verdict | null>(null);

  const list = useMemo(() => {
    const all = Object.values(verdictMap ?? {});
    const q = query.trim().toUpperCase();
    return all
      .filter((v) => (q ? v.symbol.toUpperCase().includes(q) : true))
      .filter((v) => {
        const isExec = v.verdict.toString().startsWith("EXECUTE");
        if (mode === "EXECUTE") return isExec;
        if (mode === "NON_EXECUTE") return !isExec;
        return true;
      })
      .sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0));
  }, [verdictMap, query, mode]);

  const execCount = useMemo(
    () => list.filter((v) => v.verdict.toString().startsWith("EXECUTE")).length,
    [list]
  );

  return (
    <div style={{ padding: "22px 26px", display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 900, letterSpacing: "0.06em" }}>
            SIGNALS
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
            Filter & inspect L12 verdicts. Sorted by confidence.
          </div>
        </div>
        
      </div>

      {/* Controls */}
      <div
        style={{
          display: "flex",
          gap: 10,
          flexWrap: "wrap",
          alignItems: "center",
          padding: "12px 12px",
          borderRadius: 12,
          background: "var(--bg-card)",
          border: "1px solid rgba(255,255,255,0.08)",
        }}
      >
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search pair (e.g. EURUSD)…"
          style={{
            width: 240,
            padding: "10px 12px",
            borderRadius: 10,
            border: "1px solid rgba(255,255,255,0.12)",
            background: "rgba(0,0,0,0.25)",
            color: "var(--text-primary)",
            outline: "none",
          }}
        />

        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {(["ALL", "EXECUTE", "NON_EXECUTE"] as FilterMode[]).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              style={{
                padding: "9px 10px",
                borderRadius: 10,
                border: "1px solid rgba(255,255,255,0.10)",
                background: mode === m ? "rgba(0,245,160,0.10)" : "transparent",
                color: mode === m ? "var(--text-primary)" : "var(--text-muted)",
                fontSize: 10,
                letterSpacing: "0.12em",
                fontWeight: 900,
                cursor: "pointer",
              }}
            >
              {m}
            </button>
          ))}
        </div>

        <div style={{ marginLeft: "auto", display: "flex", gap: 10, alignItems: "center" }}>
          <span
            className="badge badge-gold"
            style={{ fontSize: 9, letterSpacing: "0.12em" }}
          >
            {execCount} EXECUTE
          </span>
          <span
            className="badge badge-muted"
            style={{ fontSize: 9, letterSpacing: "0.12em" }}
          >
            {list.length} TOTAL
          </span>
        </div>
      </div>

      {/* Grid */}
      {isLoading ? (
        <div style={{ padding: "30px 0", color: "var(--text-muted)" }}>LOADING…</div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
            gap: 12,
          }}
        >
          {list.map((v) => (
            <div key={v.symbol} onClick={() => setSelected(v)}>
              <VerdictCard verdict={v} selected={selected?.symbol === v.symbol} onTake={() => setSelected(v)} onSkip={() => setSelected(v)} />
            </div>
          ))}
        </div>
      )}

      {/* TakeSignal overlay */}
      {selected && accounts && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.7)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 100,
          }}
          onClick={() => setSelected(null)}
        >
          <div onClick={(e) => e.stopPropagation()}>
            <TakeSignalForm
              verdict={selected}
              accounts={accounts}
              onDone={() => setSelected(null)}
              onCancel={() => setSelected(null)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
