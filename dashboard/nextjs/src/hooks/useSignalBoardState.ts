"use client";

// ============================================================
// useSignalBoardState — Signal Board P0 orchestration hook
// Derives: eligible / blocked / cooldown / expired / ignored
// ============================================================

import { useMemo, useState, useCallback } from "react";
import {
  useAllVerdicts,
  useAccounts,
  usePairs,
  useCalendarBlocker,
  useAccountsRiskSnapshot,
  previewRiskMulti,
  type RiskPreviewAccountItem,
} from "@/lib/api";
import type { L12Verdict } from "@/types";
import { VerdictType } from "@/types";

// ── Tab type ─────────────────────────────────────────────────
export type SignalTab = "ELIGIBLE" | "BLOCKED" | "COOLDOWN" | "EXPIRED" | "IGNORED";

// ── Urgency score (higher = more urgent) ─────────────────────
export function urgencyScore(v: L12Verdict): number {
  const conf = v.confidence ?? 0;
  const rr = v.risk_reward_ratio ?? 1;
  const now = Math.floor(Date.now() / 1000);
  // penalise signals expiring soon (within 5 min = 0.5 penalty)
  const timeBonus =
    v.expires_at && v.expires_at - now < 300
      ? 0.5
      : 1;
  return conf * rr * timeBonus;
}

// ── Expired check ─────────────────────────────────────────────
function isExpired(v: L12Verdict): boolean {
  if (!v.expires_at) return false;
  return v.expires_at < Math.floor(Date.now() / 1000);
}

// ── Blocked check (gate failures or news lock) ────────────────
function isGateBlocked(v: L12Verdict): boolean {
  if (!v.gates?.length) return false;
  return v.gates.some((g) => !g.passed);
}

// ── Is actionable verdict ─────────────────────────────────────
function isExecuteVerdict(v: L12Verdict): boolean {
  const s = String(v.verdict ?? "");
  return s === VerdictType.EXECUTE_BUY || s === VerdictType.EXECUTE_SELL || s === VerdictType.EXECUTE;
}

// ── Gate block reason ─────────────────────────────────────────
export function gateBlockReason(v: L12Verdict): string {
  const failed = v.gates?.filter((g) => !g.passed) ?? [];
  if (!failed.length) return "";
  return failed
    .map((g) => g.message ?? g.name ?? g.gate_id)
    .join("; ");
}

// ── Expiry countdown (mm:ss) ──────────────────────────────────
export function expiryCountdown(expiresAt: number): string {
  const diff = expiresAt - Math.floor(Date.now() / 1000);
  if (diff <= 0) return "EXPIRED";
  const m = Math.floor(diff / 60);
  const s = diff % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

// ─────────────────────────────────────────────────────────────

export interface SignalBoardState {
  // tabs
  activeTab: SignalTab;
  setActiveTab: (t: SignalTab) => void;

  // bucketed signals
  eligible: L12Verdict[];
  blocked: L12Verdict[];
  cooldown: L12Verdict[];
  expired: L12Verdict[];
  ignored: L12Verdict[];

  // tab counts
  counts: Record<SignalTab, number>;

  // filters
  selectedPair: string;
  setSelectedPair: (p: string) => void;

  // selection
  selectedSignal: L12Verdict | null;
  selectSignal: (v: L12Verdict | null) => void;

  // news / calendar blackout
  calendarLocked: boolean;
  calendarLockReason: string | undefined;

  // risk preview
  riskPreviews: RiskPreviewAccountItem[];
  riskPreviewLoading: boolean;
  riskPreviewError: string | null;
  runRiskPreview: (accountIds: string[], riskPercent: number, riskMode: "FIXED" | "SPLIT") => Promise<void>;
  clearRiskPreview: () => void;

  // data
  accounts: ReturnType<typeof useAccounts>["data"];
  pairs: ReturnType<typeof usePairs>["data"];
  isLoading: boolean;
  mutate: () => void;
}

export function useSignalBoardState(): SignalBoardState {
  const [activeTab, setActiveTab] = useState<SignalTab>("ELIGIBLE");
  const [selectedPair, setSelectedPair] = useState("ALL");
  const [selectedSignal, setSelectedSignal] = useState<L12Verdict | null>(null);
  const [riskPreviews, setRiskPreviews] = useState<RiskPreviewAccountItem[]>([]);
  const [riskPreviewLoading, setRiskPreviewLoading] = useState(false);
  const [riskPreviewError, setRiskPreviewError] = useState<string | null>(null);

  const { data: rawVerdicts, isLoading: vLoading, mutate: mutatePrimary } = useAllVerdicts();
  const { data: accounts } = useAccounts();
  const { data: pairs } = usePairs();
  const { data: calendarBlocker } = useCalendarBlocker();
  const { data: _riskSnapshots } = useAccountsRiskSnapshot();

  // pair-filtered verdicts
  const verdicts = useMemo(() => {
    const all = rawVerdicts ?? [];
    if (selectedPair === "ALL") return all;
    return all.filter((v) => v.symbol === selectedPair);
  }, [rawVerdicts, selectedPair]);

  const calendarLocked = calendarBlocker?.is_locked ?? false;
  const calendarLockReason = calendarBlocker?.lock_reason;

  // bucket into tabs
  const { eligible, blocked, cooldown, expired, ignored } = useMemo(() => {
    const eligible: L12Verdict[] = [];
    const blocked: L12Verdict[] = [];
    const cooldown: L12Verdict[] = [];
    const expired: L12Verdict[] = [];
    const ignored: L12Verdict[] = [];

    for (const v of verdicts) {
      // expired first — takes precedence
      if (isExpired(v)) {
        expired.push(v);
        continue;
      }

      const verdict = String(v.verdict ?? "");

      // non-execute verdicts → ignored
      if (!isExecuteVerdict(v)) {
        ignored.push(v);
        continue;
      }

      // news lock → blocked
      if (calendarLocked) {
        blocked.push(v);
        continue;
      }

      // gate failures → blocked
      if (isGateBlocked(v)) {
        blocked.push(v);
        continue;
      }

      // cooldown state from execution
      if (v.wolf_status === "COOLDOWN") {
        cooldown.push(v);
        continue;
      }

      eligible.push(v);
    }

    // sort eligible by urgency desc
    eligible.sort((a, b) => urgencyScore(b) - urgencyScore(a));
    blocked.sort((a, b) => urgencyScore(b) - urgencyScore(a));

    return { eligible, blocked, cooldown, expired, ignored };
  }, [verdicts, calendarLocked]);

  const counts: Record<SignalTab, number> = {
    ELIGIBLE: eligible.length,
    BLOCKED: blocked.length,
    COOLDOWN: cooldown.length,
    EXPIRED: expired.length,
    IGNORED: ignored.length,
  };

  const selectSignal = useCallback((v: L12Verdict | null) => {
    setSelectedSignal(v);
    setRiskPreviews([]);
    setRiskPreviewError(null);
  }, []);

  const runRiskPreview = useCallback(
    async (accountIds: string[], riskPercent: number, riskMode: "FIXED" | "SPLIT") => {
      if (!selectedSignal || !accountIds.length) return;
      setRiskPreviewLoading(true);
      setRiskPreviewError(null);
      try {
        const result = await previewRiskMulti({
          verdict_id: `${selectedSignal.symbol}_${selectedSignal.timestamp}`,
          accounts: accountIds.map((account_id) => ({ account_id })),
          risk_percent: riskPercent,
          risk_mode: riskMode,
        });
        setRiskPreviews(result?.previews ?? []);
      } catch (e) {
        setRiskPreviewError(e instanceof Error ? e.message : "Risk preview failed");
      } finally {
        setRiskPreviewLoading(false);
      }
    },
    [selectedSignal]
  );

  const clearRiskPreview = useCallback(() => {
    setRiskPreviews([]);
    setRiskPreviewError(null);
  }, []);

  const mutate = useCallback(() => {
    mutatePrimary();
  }, [mutatePrimary]);

  return {
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
    isLoading: vLoading,
    mutate,
  };
}
