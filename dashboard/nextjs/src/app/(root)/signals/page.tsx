"use client";

// ============================================================
// TUYUL FX Wolf-15 — Signal Explorer (/signals)
// Full L12 verdict board: card grid + detail panel + summary table.
// Data: REST bootstrap (30s poll) + WS live merge.
// ============================================================

import { useMemo, useState, useCallback } from "react";
import Link from "next/link";
import { VerdictCard } from "@/components/VerdictCard";
import { SignalDetailPanel } from "@/components/SignalDetailPanel";
import VerdictEmptyStatePanel from "@/components/feedback/VerdictEmptyStatePanel";
import { useAllVerdicts, useHealth } from "@/lib/api";
import { useLiveSignals } from "@/lib/realtime/hooks/useLiveSignals";
import { useFilteredSignals } from "@/lib/realtime/hooks/useFilteredSignals";
import { useSignalNotifications } from "@/lib/realtime/hooks/useSignalNotifications";
import { classifyVerdictEmptyState } from "@/lib/verdictEmptyState";
import { useSystemStore } from "@/store/useSystemStore";
import { formatTime } from "@/lib/timezone";
import type { L12Verdict } from "@/types";

type FilterMode = "ALL" | "EXECUTE" | "NON_EXECUTE" | "HIGH_PROB";
type ViewMode = "GRID" | "TABLE";

// ── Helpers ──────────────────────────────────────────────────

function directionLabel(v: L12Verdict): string {
  if (v.direction) return v.direction;
  const vs = String(v.verdict ?? "");
  if (vs.includes("BUY")) return "BUY";
  if (vs.includes("SELL")) return "SELL";
  return "—";
}

function directionColor(d: string): string {
  if (d === "BUY") return "var(--cyan)";
  if (d === "SELL") return "var(--red)";
  return "var(--text-muted)";
}

function verdictColor(v: string): string {
  if (v.startsWith("EXECUTE")) return "var(--green)";
  if (v === "HOLD") return "var(--yellow)";
  if (v === "ABORT") return "var(--red)";
  return "var(--text-muted)";
}

function gatePassCount(v: L12Verdict): string {
  if (!v.gates?.length) return "—";
  const passed = v.gates.filter((g) => g.passed).length;
  return `${passed}/${v.gates.length}`;
}

// ── Signal Summary Table ─────────────────────────────────────

function SignalSummaryTable({
  signals,
  selectedSymbol,
  onSelect,
}: {
  signals: L12Verdict[];
  selectedSymbol: string | null;
  onSelect: (v: L12Verdict) => void;
}) {
  return (
    <div
      style={{
        borderRadius: 10,
        border: "1px solid rgba(255,255,255,0.08)",
        overflow: "hidden",
      }}
    >
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontSize: 11,
          fontFamily: "var(--font-mono)",
        }}
      >
        <thead>
          <tr
            style={{
              background: "rgba(0,0,0,0.4)",
              borderBottom: "1px solid rgba(255,255,255,0.08)",
            }}
          >
            {["PAIR", "DIR", "VERDICT", "CONF", "WOLF", "TII", "FRPC", "R:R", "GATES", "TIME"].map(
              (h) => (
                <th
                  key={h}
                  style={{
                    padding: "8px 8px",
                    textAlign: "left",
                    fontSize: 8,
                    fontWeight: 800,
                    letterSpacing: "0.12em",
                    color: "var(--text-faint)",
                    whiteSpace: "nowrap",
                  }}
                >
                  {h}
                </th>
              )
            )}
          </tr>
        </thead>
        <tbody>
          {signals.map((v) => {
            const vs = String(v.verdict ?? "");
            const dir = directionLabel(v);
            const isSelected = selectedSymbol === v.symbol;
            return (
              <tr
                key={v.symbol}
                onClick={() => onSelect(v)}
                style={{
                  cursor: "pointer",
                  background: isSelected
                    ? "rgba(0,229,255,0.06)"
                    : "transparent",
                  borderBottom: "1px solid rgba(255,255,255,0.04)",
                  transition: "background 0.15s",
                }}
                onMouseEnter={(e) => {
                  if (!isSelected) e.currentTarget.style.background = "rgba(255,255,255,0.03)";
                }}
                onMouseLeave={(e) => {
                  if (!isSelected) e.currentTarget.style.background = "transparent";
                }}
              >
                <td style={{ padding: "7px 8px", fontWeight: 700, color: "var(--text-primary)" }}>
                  {v.symbol}
                </td>
                <td style={{ padding: "7px 8px" }}>
                  <span
                    style={{
                      color: directionColor(dir),
                      fontWeight: 800,
                      fontSize: 10,
                    }}
                  >
                    {dir === "BUY" ? "▲" : dir === "SELL" ? "▼" : ""} {dir}
                  </span>
                </td>
                <td style={{ padding: "7px 8px" }}>
                  <span
                    style={{
                      fontSize: 9,
                      fontWeight: 700,
                      padding: "2px 6px",
                      borderRadius: 4,
                      color: verdictColor(vs),
                      background: vs.startsWith("EXECUTE")
                        ? "rgba(0,230,118,0.08)"
                        : vs === "HOLD"
                          ? "rgba(255,215,64,0.08)"
                          : vs === "ABORT"
                            ? "rgba(255,61,87,0.08)"
                            : "rgba(255,255,255,0.04)",
                      letterSpacing: "0.04em",
                    }}
                  >
                    {vs}
                  </span>
                </td>
                <td style={{ padding: "7px 8px" }}>
                  <span className="num" style={{ color: (v.confidence ?? 0) >= 0.75 ? "var(--green)" : "var(--text-secondary)" }}>
                    {((v.confidence ?? 0) * 100).toFixed(0)}%
                  </span>
                </td>
                <td style={{ padding: "7px 8px", color: v.scores && v.scores.wolf_score >= 21 ? "var(--green)" : "var(--text-muted)" }}>
                  {v.scores?.wolf_score?.toFixed(0) ?? "—"}
                </td>
                <td style={{ padding: "7px 8px", color: v.scores && v.scores.tii_score >= 0.90 ? "var(--green)" : "var(--text-muted)" }}>
                  {v.scores?.tii_score?.toFixed(2) ?? "—"}
                </td>
                <td style={{ padding: "7px 8px", color: v.scores && v.scores.frpc_score >= 0.93 ? "var(--green)" : "var(--text-muted)" }}>
                  {v.scores?.frpc_score?.toFixed(2) ?? "—"}
                </td>
                <td style={{ padding: "7px 8px" }}>
                  <span
                    className="num"
                    style={{
                      color: v.risk_reward_ratio
                        ? v.risk_reward_ratio >= 2
                          ? "var(--green)"
                          : "var(--yellow)"
                        : "var(--text-muted)",
                    }}
                  >
                    {v.risk_reward_ratio ? `1:${v.risk_reward_ratio.toFixed(1)}` : "—"}
                  </span>
                </td>
                <td style={{ padding: "7px 8px", color: "var(--text-muted)" }}>
                  {gatePassCount(v)}
                </td>
                <td style={{ padding: "7px 8px", color: "var(--text-faint)", fontSize: 9 }}>
                  {formatTime(v.timestamp * 1000)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Main Page ────────────────────────────────────────────────

export default function SignalsPage() {
  const { data: verdictsRaw, isLoading, mutate } = useAllVerdicts();
  const { data: health } = useHealth();
  const systemMode = useSystemStore((s) => s.mode);
  const wsStatus = useSystemStore((s) => s.wsStatus);

  const restVerdicts = useMemo(() => verdictsRaw ?? [], [verdictsRaw]);
  const {
    verdicts,
    status: liveStatus,
    isStale: verdictStale,
  } = useLiveSignals(restVerdicts, true);

  // High-probability EXECUTE filter (confidence >= 0.75, active only)
  const highProbSignals = useFilteredSignals(verdicts, {
    executeOnly: true,
    minConfidence: 0.75,
    activeOnly: true,
  });

  // Browser notifications for new high-probability signals
  useSignalNotifications(highProbSignals);

  const [query, setQuery] = useState("");
  const [filterMode, setFilterMode] = useState<FilterMode>("ALL");
  const [viewMode, setViewMode] = useState<ViewMode>("GRID");
  const [selectedVerdict, setSelectedVerdict] = useState<L12Verdict | null>(null);

  const list = useMemo(() => {
    // HIGH_PROB mode uses precomputed filtered list
    if (filterMode === "HIGH_PROB") {
      const q = query.trim().toUpperCase();
      return highProbSignals
        .filter((v) => (q ? v.symbol.toUpperCase().includes(q) : true))
        .sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0));
    }

    const all = verdicts ?? [];
    const q = query.trim().toUpperCase();
    return all
      .filter((v) => (q ? v.symbol.toUpperCase().includes(q) : true))
      .filter((v) => {
        const isExec = v.verdict.toString().startsWith("EXECUTE");
        if (filterMode === "EXECUTE") return isExec;
        if (filterMode === "NON_EXECUTE") return !isExec;
        return true;
      })
      .sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0));
  }, [verdicts, highProbSignals, query, filterMode]);

  const verdictEmptyState = useMemo(
    () =>
      classifyVerdictEmptyState({
        verdictCount: list.length,
        isLoading,
        verdictStale,
        liveStatus,
        mode: systemMode,
        wsStatus,
        feedStatus: health?.feed_status,
      }),
    [list.length, isLoading, verdictStale, liveStatus, systemMode, wsStatus, health?.feed_status]
  );

  const execCount = useMemo(
    () => list.filter((v) => v.verdict.toString().startsWith("EXECUTE")).length,
    [list]
  );

  const holdCount = useMemo(
    () => list.filter((v) => v.verdict === "HOLD").length,
    [list]
  );

  const handleSelectVerdict = useCallback((v: L12Verdict) => {
    setSelectedVerdict((prev) => (prev?.symbol === v.symbol ? null : v));
  }, []);

  return (
    <div style={{ padding: "22px 26px", display: "flex", flexDirection: "column", gap: 16 }}>
      {/* ── Header ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 900, letterSpacing: "0.06em" }}>
            L12 SIGNAL BOARD
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
            Layer-12 constitutional verdict results — live feed. Click any signal for full analysis.
          </div>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <Link
            href="/trades/signals"
            style={{
              padding: "8px 14px",
              borderRadius: 8,
              border: "1px solid var(--accent)",
              background: "rgba(0,229,255,0.06)",
              color: "var(--accent)",
              fontSize: 10,
              fontWeight: 800,
              fontFamily: "var(--font-mono)",
              textDecoration: "none",
              letterSpacing: "0.06em",
            }}
          >
            SIGNAL QUEUE →
          </Link>
        </div>
      </div>

      {/* ── Summary Strip ── */}
      <div
        style={{
          display: "flex",
          gap: 0,
          borderRadius: 8,
          border: "1px solid var(--border-default)",
          overflow: "hidden",
          background: "var(--bg-panel)",
        }}
      >
        {[
          { label: "TOTAL PAIRS", value: list.length, color: "var(--text-primary)" },
          { label: "EXECUTE", value: execCount, color: "var(--green)", pulse: execCount > 0 },
          { label: "HIGH PROB", value: highProbSignals.length, color: highProbSignals.length > 0 ? "var(--green)" : "var(--text-muted)", pulse: highProbSignals.length > 0 },
          { label: "HOLD", value: holdCount, color: "var(--yellow)" },
          { label: "NO TRADE", value: list.length - execCount - holdCount, color: "var(--text-muted)" },
          { label: "LIVE STATUS", value: liveStatus, color: liveStatus === "LIVE" ? "var(--green)" : liveStatus === "STALE" ? "var(--red)" : "var(--yellow)" },
        ].map((item, i) => (
          <div
            key={item.label}
            style={{
              flex: 1,
              padding: "10px 14px",
              borderRight: i < 5 ? "1px solid var(--border-default)" : "none",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 2,
            }}
          >
            <span
              style={{
                fontSize: 8,
                fontWeight: 800,
                letterSpacing: "0.10em",
                color: "var(--text-faint)",
                fontFamily: "var(--font-mono)",
              }}
            >
              {item.label}
            </span>
            <span
              className="num"
              style={{
                fontSize: 16,
                fontWeight: 800,
                color: item.color,
                fontFamily: "var(--font-mono)",
              }}
            >
              {item.value}
            </span>
          </div>
        ))}
      </div>

      {/* ── Controls ── */}
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
          name="signal_search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search pair (e.g. EURUSD)…"
          style={{
            width: 220,
            padding: "10px 12px",
            borderRadius: 10,
            border: "1px solid rgba(255,255,255,0.12)",
            background: "rgba(0,0,0,0.25)",
            color: "var(--text-primary)",
            outline: "none",
            fontSize: 12,
          }}
        />

        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          {(["ALL", "EXECUTE", "HIGH_PROB", "NON_EXECUTE"] as FilterMode[]).map((m) => (
            <button
              key={m}
              onClick={() => setFilterMode(m)}
              style={{
                padding: "8px 10px",
                borderRadius: 8,
                border: "1px solid rgba(255,255,255,0.10)",
                background: filterMode === m ? "rgba(0,245,160,0.10)" : "transparent",
                color: filterMode === m ? "var(--text-primary)" : "var(--text-muted)",
                fontSize: 10,
                letterSpacing: "0.10em",
                fontWeight: 800,
                cursor: "pointer",
                fontFamily: "var(--font-mono)",
              }}
            >
              {m}
            </button>
          ))}
        </div>

        {/* View mode toggle */}
        <div style={{ display: "flex", gap: 4, marginLeft: 6, alignItems: "center" }}>
          {(["GRID", "TABLE"] as ViewMode[]).map((m) => (
            <button
              key={m}
              onClick={() => setViewMode(m)}
              style={{
                padding: "7px 10px",
                borderRadius: 6,
                border: "1px solid rgba(255,255,255,0.10)",
                background: viewMode === m ? "rgba(0,229,255,0.10)" : "transparent",
                color: viewMode === m ? "var(--accent)" : "var(--text-muted)",
                fontSize: 9,
                letterSpacing: "0.10em",
                fontWeight: 800,
                cursor: "pointer",
                fontFamily: "var(--font-mono)",
              }}
            >
              {m === "GRID" ? "◫ GRID" : "≡ TABLE"}
            </button>
          ))}
        </div>

        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          <button
            onClick={() => mutate()}
            style={{
              padding: "7px 12px",
              borderRadius: 6,
              border: "1px solid rgba(255,255,255,0.10)",
              background: "transparent",
              color: "var(--text-muted)",
              fontSize: 9,
              fontWeight: 700,
              cursor: "pointer",
              fontFamily: "var(--font-mono)",
              letterSpacing: "0.06em",
            }}
          >
            ↻ REFRESH
          </button>
          {verdictStale && (
            <span
              style={{
                fontSize: 9,
                color: "var(--yellow)",
                fontWeight: 700,
                fontFamily: "var(--font-mono)",
                padding: "3px 8px",
                borderRadius: 4,
                background: "rgba(255,215,64,0.08)",
                letterSpacing: "0.06em",
              }}
            >
              STALE
            </span>
          )}
        </div>
      </div>

      {/* ── Content: two-column when detail selected ── */}
      {isLoading ? (
        <div style={{ padding: "30px 0", color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 12 }}>
          LOADING VERDICTS…
        </div>
      ) : list.length === 0 ? (
        <VerdictEmptyStatePanel
          state={verdictEmptyState}
          fallbackDetail="Adjust filter or wait for the next L12 cycle."
        />
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: selectedVerdict ? "1fr 380px" : "1fr",
            gap: 16,
            alignItems: "start",
          }}
        >
          {/* ── Left: card grid or table ── */}
          <div>
            {viewMode === "TABLE" ? (
              <SignalSummaryTable
                signals={list}
                selectedSymbol={selectedVerdict?.symbol ?? null}
                onSelect={handleSelectVerdict}
              />
            ) : (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: selectedVerdict
                    ? "repeat(auto-fill, minmax(260px, 1fr))"
                    : "repeat(auto-fill, minmax(280px, 1fr))",
                  gap: 12,
                }}
              >
                {list.map((v) => (
                  <div
                    key={v.symbol}
                    onClick={() => handleSelectVerdict(v)}
                  >
                    <VerdictCard
                      verdict={v}
                      selected={selectedVerdict?.symbol === v.symbol}
                    />
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* ── Right: detail panel ── */}
          {selectedVerdict && (
            <SignalDetailPanel
              verdict={selectedVerdict}
              onClose={() => setSelectedVerdict(null)}
            />
          )}
        </div>
      )}
    </div>
  );
}
