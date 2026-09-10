"use client";

// ============================================================
// TUYUL FX Wolf-15 — Signal Board (/trades/signals) P0
// Flow: View EXECUTE verdicts → TAKE or SKIP
// State: Eligible / Blocked / Cooldown / Expired / Ignored
// ============================================================

import { useSignalBoardState, type SignalTab } from "@/hooks/useSignalBoardState";
import { SignalRowCard } from "@/components/signal-board/SignalRowCard";
import { SignalDetailPanel } from "@/components/signal-board/SignalDetailPanel";

const TABS: SignalTab[] = ["ELIGIBLE", "BLOCKED", "COOLDOWN", "EXPIRED", "IGNORED"];

export default function SignalBoardPage() {
  const state = useSignalBoardState();

  const {
    activeTab,
    setActiveTab,
    eligible,
    blocked,
    cooldown,
    expired,
    ignored,
    counts,
    selectedPair,
    setSelectedPair,
    selectedSignal,
    selectSignal,
    calendarLocked,
    calendarLockReason,
    riskPreviews,
    riskPreviewLoading,
    riskPreviewError,
    runRiskPreview,
    clearRiskPreview,
    accounts,
    pairs,
    isLoading,
    mutate,
  } = state;

  const tabSignals = (() => {
    switch (activeTab) {
      case "ELIGIBLE":
        return eligible;
      case "BLOCKED":
        return blocked;
      case "COOLDOWN":
        return cooldown;
      case "EXPIRED":
        return expired;
      case "IGNORED":
        return ignored;
    }
  })();

  function handleDone() {
    selectSignal(null);
    clearRiskPreview();
    mutate();
  }

  return (
    <div style={{ padding: "24px 28px", display: "flex", flexDirection: "column", gap: 18 }}>
      {/* ── Header ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div>
          <h1
            style={{
              fontSize: 20,
              fontWeight: 700,
              letterSpacing: "0.05em",
              color: "var(--text-primary)",
              margin: 0,
            }}
          >
            SIGNAL BOARD
          </h1>
          <p
            style={{
              fontSize: 11,
              color: "var(--text-muted)",
              marginTop: 2,
              letterSpacing: "0.02em",
            }}
          >
            TAKE or SKIP execution verdicts
          </p>
        </div>

        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          {counts.ELIGIBLE > 0 && (
            <span className="badge badge-blue">
              {counts.ELIGIBLE} ELIGIBLE
            </span>
          )}
          {counts.BLOCKED > 0 && (
            <span className="badge badge-red">
              {counts.BLOCKED} BLOCKED
            </span>
          )}
        </div>
      </div>

      {/* ── Controls ── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "10px 14px",
          borderRadius: "var(--radius-md)",
          background: "var(--bg-panel)",
          border: "1px solid var(--border-default)",
        }}
      >
        {/* Tabs */}
        {TABS.map((tab) => {
          const count = counts[tab];
          const active = activeTab === tab;
          return (
            <button
              key={tab}
              className="btn btn-ghost"
              style={{
                fontSize: 11,
                padding: "6px 12px",
                fontWeight: active ? 700 : 500,
                opacity: active ? 1 : 0.5,
                borderColor: active ? "var(--accent)" : "transparent",
                color: active ? "var(--accent)" : "var(--text-muted)",
                position: "relative",
              }}
              onClick={() => setActiveTab(tab)}
            >
              {tab}
              {count > 0 && (
                <span
                  style={{
                    marginLeft: 6,
                    background: active ? "var(--accent)" : "rgba(255,255,255,0.1)",
                    color: active ? "#000" : "var(--text-muted)",
                    borderRadius: 8,
                    padding: "1px 5px",
                    fontSize: 9,
                    fontWeight: 800,
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  {count}
                </span>
              )}
            </button>
          );
        })}

        {/* Pair filter */}
        <select
          value={selectedPair}
          onChange={(e) => setSelectedPair(e.target.value)}
          style={{ fontSize: 11, padding: "6px 10px", marginLeft: "auto" }}
        >
          <option value="ALL">ALL PAIRS</option>
          {(pairs ?? []).map((p) => (
            <option key={p.symbol} value={p.symbol}>
              {p.symbol}
            </option>
          ))}
        </select>

        {/* Refresh */}
        <button className="btn btn-ghost" style={{ fontSize: 11 }} onClick={mutate}>
          ↻ REFRESH
        </button>
      </div>

      {/* ── Two-column layout: verdict list + detail ── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: selectedSignal ? "1fr 400px" : "1fr",
          gap: 20,
          alignItems: "start",
        }}
      >
        {/* ── Left: signal cards ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {isLoading && (
            <div
              style={{
                fontSize: 12,
                color: "var(--text-muted)",
                padding: 24,
                textAlign: "center",
              }}
            >
              Loading signals...
            </div>
          )}

          {!isLoading && tabSignals.length === 0 && (
            <div
              className="card"
              style={{
                fontSize: 12,
                color: "var(--text-muted)",
                padding: "32px",
                textAlign: "center",
              }}
            >
              {activeTab === "ELIGIBLE" && "No eligible signals. Wait for new verdicts or check other tabs."}
              {activeTab === "BLOCKED" && "No blocked signals. All clear!"}
              {activeTab === "COOLDOWN" && "No signals in cooldown."}
              {activeTab === "EXPIRED" && "No expired signals."}
              {activeTab === "IGNORED" && "No ignored signals (HOLD/NO_TRADE verdicts)."}
            </div>
          )}

          {tabSignals.map((v) => (
            <SignalRowCard
              key={`${v.symbol}_${v.timestamp}`}
              verdict={v}
              tab={activeTab}
              selected={selectedSignal?.symbol === v.symbol && selectedSignal?.timestamp === v.timestamp}
              calendarLocked={calendarLocked}
              calendarLockReason={calendarLockReason}
              onSelect={() => selectSignal(v)}
            />
          ))}
        </div>

        {/* ── Right: detail panel ── */}
        {selectedSignal && accounts && (
          <SignalDetailPanel
            signal={selectedSignal}
            accounts={accounts}
            riskPreviews={riskPreviews}
            riskPreviewLoading={riskPreviewLoading}
            riskPreviewError={riskPreviewError}
            calendarLocked={calendarLocked}
            calendarLockReason={calendarLockReason}
            onRunPreview={runRiskPreview}
            onDone={handleDone}
            onClose={() => {
              selectSignal(null);
              clearRiskPreview();
            }}
          />
        )}
      </div>
    </div>
  );
}
