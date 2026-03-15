"use client";

// ============================================================
// TUYUL FX Wolf-15 — useSignalExplorerState
// Signal Explorer (research surface, NOT execution queue)
// - bootstrap: GET /api/v1/verdict/all
// - live merge: /ws/verdict
// - compare mode: up to 2 signals side-by-side
// - deep rationale: gate breakdown + L12 scores per signal
// ============================================================

import { useMemo, useState, useCallback } from "react";
import { useAllVerdicts, useContext } from "@/lib/api";
import type { L12Verdict, ContextSnapshot } from "@/types";

// ─── Filter / sort types ─────────────────────────────────────

export type ExplorerVerdictFilter = "ALL" | "EXECUTE" | "HOLD" | "NO_TRADE" | "ABORT";
export type ExplorerSessionFilter = "ALL" | "LONDON" | "NEW_YORK" | "ASIA" | "OVERLAP";
export type ExplorerSortKey = "confidence" | "rr" | "wolf" | "tii" | "frpc" | "timestamp";
export type ExplorerSortDir = "desc" | "asc";

export interface ExplorerFilters {
  query: string;
  verdictFilter: ExplorerVerdictFilter;
  sessionFilter: ExplorerSessionFilter;
  sortKey: ExplorerSortKey;
  sortDir: ExplorerSortDir;
  showOnlyGatesPassed: boolean;
}

const DEFAULT_FILTERS: ExplorerFilters = {
  query: "",
  verdictFilter: "ALL",
  sessionFilter: "ALL",
  sortKey: "confidence",
  sortDir: "desc",
  showOnlyGatesPassed: false,
};

// ─── Compare mode ────────────────────────────────────────────

export interface CompareSlot {
  a: L12Verdict | null;
  b: L12Verdict | null;
}

// ─── Hook return type ─────────────────────────────────────────

export interface SignalExplorerState {
  // data
  allVerdicts: L12Verdict[];
  filteredVerdicts: L12Verdict[];
  context: ContextSnapshot | undefined;
  isLoading: boolean;
  isError: boolean;

  // filters
  filters: ExplorerFilters;
  setQuery: (q: string) => void;
  setVerdictFilter: (f: ExplorerVerdictFilter) => void;
  setSessionFilter: (f: ExplorerSessionFilter) => void;
  setSortKey: (k: ExplorerSortKey) => void;
  toggleSortDir: () => void;
  toggleGateFilter: () => void;
  resetFilters: () => void;

  // inspector
  inspected: L12Verdict | null;
  setInspected: (v: L12Verdict | null) => void;

  // compare mode
  compareMode: boolean;
  setCompareMode: (on: boolean) => void;
  compareSlots: CompareSlot;
  toggleCompare: (v: L12Verdict) => void;
  clearCompare: () => void;

  // derived counts
  counts: {
    total: number;
    execute: number;
    hold: number;
    noTrade: number;
    abort: number;
    filtered: number;
  };
}

// ─── Hook ─────────────────────────────────────────────────────

export function useSignalExplorerState(): SignalExplorerState {
  const { data: allVerdicts = [], isLoading, isError } = useAllVerdicts();
  const { data: context } = useContext();

  const [filters, setFilters] = useState<ExplorerFilters>(DEFAULT_FILTERS);
  const [inspected, setInspected] = useState<L12Verdict | null>(null);
  const [compareMode, setCompareMode] = useState(false);
  const [compareSlots, setCompareSlots] = useState<CompareSlot>({ a: null, b: null });

  // ── filter + sort ────────────────────────────────────────
  const filteredVerdicts = useMemo(() => {
    const q = filters.query.trim().toUpperCase();

    let list = allVerdicts.filter((v) => {
      if (q && !v.symbol.toUpperCase().includes(q)) return false;

      if (filters.verdictFilter !== "ALL") {
        const vStr = String(v.verdict ?? "");
        switch (filters.verdictFilter) {
          case "EXECUTE":
            if (!vStr.startsWith("EXECUTE")) return false;
            break;
          case "HOLD":
            if (vStr !== "HOLD") return false;
            break;
          case "NO_TRADE":
            if (vStr !== "NO_TRADE") return false;
            break;
          case "ABORT":
            if (vStr !== "ABORT") return false;
            break;
        }
      }

      if (filters.sessionFilter !== "ALL" && v.session) {
        if (!v.session.toUpperCase().includes(filters.sessionFilter)) return false;
      }

      if (filters.showOnlyGatesPassed) {
        const allPassed = v.gates?.every((g) => g.passed) ?? false;
        if (!allPassed) return false;
      }

      return true;
    });

    // ── sort ────────────────────────────────────────────────
    list = list.sort((a, b) => {
      let diff = 0;
      switch (filters.sortKey) {
        case "confidence":
          diff = (a.confidence ?? 0) - (b.confidence ?? 0);
          break;
        case "rr":
          diff = (a.risk_reward_ratio ?? 0) - (b.risk_reward_ratio ?? 0);
          break;
        case "wolf":
          diff = (a.scores?.wolf_score ?? 0) - (b.scores?.wolf_score ?? 0);
          break;
        case "tii":
          diff = (a.scores?.tii_score ?? 0) - (b.scores?.tii_score ?? 0);
          break;
        case "frpc":
          diff = (a.scores?.frpc_score ?? 0) - (b.scores?.frpc_score ?? 0);
          break;
        case "timestamp":
          diff = a.timestamp - b.timestamp;
          break;
      }
      return filters.sortDir === "desc" ? -diff : diff;
    });

    return list;
  }, [allVerdicts, filters]);

  // ── derived counts ───────────────────────────────────────
  const counts = useMemo(() => {
    const execute = allVerdicts.filter((v) => String(v.verdict).startsWith("EXECUTE")).length;
    const hold = allVerdicts.filter((v) => String(v.verdict) === "HOLD").length;
    const noTrade = allVerdicts.filter((v) => String(v.verdict) === "NO_TRADE").length;
    const abort = allVerdicts.filter((v) => String(v.verdict) === "ABORT").length;
    return { total: allVerdicts.length, execute, hold, noTrade, abort, filtered: filteredVerdicts.length };
  }, [allVerdicts, filteredVerdicts.length]);

  // ── compare logic ────────────────────────────────────────
  const toggleCompare = useCallback((v: L12Verdict) => {
    setCompareSlots((prev) => {
      if (prev.a?.symbol === v.symbol) return { ...prev, a: null };
      if (prev.b?.symbol === v.symbol) return { ...prev, b: null };
      if (!prev.a) return { ...prev, a: v };
      if (!prev.b) return { ...prev, b: v };
      // Both full — replace slot A and shift B→A
      return { a: prev.b, b: v };
    });
  }, []);

  const clearCompare = useCallback(() => {
    setCompareSlots({ a: null, b: null });
  }, []);

  // ── filter setters ───────────────────────────────────────
  const setQuery = useCallback((q: string) => setFilters((f) => ({ ...f, query: q })), []);
  const setVerdictFilter = useCallback((vf: ExplorerVerdictFilter) => setFilters((f) => ({ ...f, verdictFilter: vf })), []);
  const setSessionFilter = useCallback((sf: ExplorerSessionFilter) => setFilters((f) => ({ ...f, sessionFilter: sf })), []);
  const setSortKey = useCallback((k: ExplorerSortKey) => setFilters((f) => ({ ...f, sortKey: k })), []);
  const toggleSortDir = useCallback(() => setFilters((f) => ({ ...f, sortDir: f.sortDir === "desc" ? "asc" : "desc" })), []);
  const toggleGateFilter = useCallback(() => setFilters((f) => ({ ...f, showOnlyGatesPassed: !f.showOnlyGatesPassed })), []);
  const resetFilters = useCallback(() => setFilters(DEFAULT_FILTERS), []);

  return {
    allVerdicts,
    filteredVerdicts,
    context,
    isLoading,
    isError,
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
  };
}
