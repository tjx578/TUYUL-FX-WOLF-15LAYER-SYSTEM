"use client";

// ============================================================
// TUYUL FX Wolf-15 — Signal Explorer
// Path: /signals
// Research surface — deep L12 inspection with compare + rationale
// NO execution from here — TAKE redirects to Signal Board
// ============================================================

import { useMemo } from "react";
import { useSignalExplorerState } from "@/hooks/useSignalExplorerState";
import { SignalInspectorHeader } from "@/components/signal-explorer/SignalInspectorHeader";
import { ExplorerFiltersBar } from "@/components/signal-explorer/ExplorerFiltersBar";
import { SignalComparePanel } from "@/components/signal-explorer/SignalComparePanel";
import { SignalRationaleDrawer } from "@/components/signal-explorer/SignalRationaleDrawer";
import { VerdictCard } from "@/components/VerdictCard";
import type { L12Verdict } from "@/types";

export default function SignalExplorerPage() {
  const state = useSignalExplorerState();

  const {
    filteredVerdicts,
    context,
    isLoading,
    filters,
    setQuery,
    setVerdictFilter,
    setSessionFilter,
    setSortKey,
    toggleSortDir,
    toggleGateFilter,
    resetFilters,
    inspected,
    setInspected,
    compareMode,
    setCompareMode,
    compareSlots,
    toggleCompare,
    clearCompare,
    counts,
  } = state;

  const compareCount = useMemo(
    () => [compareSlots.a, compareSlots.b].filter(Boolean).length,
    [compareSlots]
  );

  const handleCardClick = (v: L12Verdict) => {
    if (compareMode) {
      toggleCompare(v);
    } else {
      setInspected(v);
    }
  };

  const handleRemoveFromCompare = (symbol: string) => {
    if (compareSlots.a?.symbol === symbol) {
      toggleCompare(compareSlots.a);
    }
    if (compareSlots.b?.symbol === symbol) {
      toggleCompare(compareSlots.b);
    }
  };

  return (
    <div style={{ padding: "22px 26px", display: "flex", flexDirection: "column", gap: 18 }}>
      {/* Header */}
      <SignalInspectorHeader
        context={context}
        totalCount={counts.total}
        filteredCount={counts.filtered}
        compareMode={compareMode}
        compareCount={compareCount}
      />

      {/* Filters bar */}
      <ExplorerFiltersBar
        filters={filters}
        counts={counts}
        compareMode={compareMode}
        onQueryChange={setQuery}
        onVerdictFilter={setVerdictFilter}
        onSessionFilter={setSessionFilter}
        onSortKey={setSortKey}
        onToggleSortDir={toggleSortDir}
        onToggleGateFilter={toggleGateFilter}
        onReset={resetFilters}
        onToggleCompareMode={() => setCompareMode(!compareMode)}
      />

      {/* Compare panel (visible if mode ON and ≥1 selected) */}
      {compareMode && compareCount > 0 && (
        <SignalComparePanel
          slots={compareSlots}
          onClear={clearCompare}
          onRemove={handleRemoveFromCompare}
        />
      )}

      {/* Main layout: grid + optional rationale drawer */}
      <div style={{ display: "flex", gap: 16 }}>
        {/* Signal grid */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {isLoading ? (
            <div
              style={{
                padding: "40px 0",
                textAlign: "center",
                fontSize: 11,
                color: "var(--text-muted)",
                letterSpacing: "0.08em",
              }}
            >
              LOADING VERDICTS…
            </div>
          ) : filteredVerdicts.length === 0 ? (
            <div
              style={{
                padding: "60px 0",
                textAlign: "center",
                fontSize: 11,
                color: "var(--text-muted)",
                letterSpacing: "0.08em",
              }}
            >
              No signals match the current filters.
            </div>
          ) : (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
                gap: 12,
              }}
            >
              {filteredVerdicts.map((v) => {
                const selected = inspected?.symbol === v.symbol;
                const inCompare =
                  compareSlots.a?.symbol === v.symbol ||
                  compareSlots.b?.symbol === v.symbol;
                return (
                  <div
                    key={v.symbol}
                    onClick={() => handleCardClick(v)}
                    style={{
                      position: "relative",
                      cursor: "pointer",
                      opacity: inCompare ? 0.6 : 1,
                    }}
                  >
                    <VerdictCard
                      verdict={v}
                      selected={compareMode ? inCompare : selected}
                    />
                    {inCompare && compareMode && (
                      <div
                        style={{
                          position: "absolute",
                          top: 8,
                          right: 8,
                          width: 20,
                          height: 20,
                          borderRadius: "50%",
                          background: "var(--cyan)",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          fontSize: 11,
                          color: "#000",
                          fontWeight: 800,
                          boxShadow: "0 0 12px rgba(0,212,255,0.60)",
                        }}
                      >
                        ✓
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Rationale drawer (only if NOT in compare mode and something selected) */}
        {!compareMode && inspected && (
          <SignalRationaleDrawer
            verdict={inspected}
            onClose={() => setInspected(null)}
          />
        )}
      </div>
    </div>
  );
}
