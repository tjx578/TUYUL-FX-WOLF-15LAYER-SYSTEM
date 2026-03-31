"use client";

/**
 * LotSizeCalculator — Account-Aware
 *
 * Menghitung lot size optimal berdasarkan:
 * - Balance/equity akun yang dipilih
 * - Risk % per trade (dari prop firm rules akun)
 * - Stop loss dalam pips
 * - Pair yang ditrade
 * - Sisa daily drawdown yang tersedia
 * - Slot trade yang masih tersedia
 */

import React, { useState, useMemo, useCallback, useEffect } from "react";
import { useAccounts } from "@/features/accounts/api/accounts.api";
import { useLiveRisk } from "@/lib/realtime/hooks/useLiveRisk";
import type { Account, RiskSnapshot } from "@/types";

// ─── Pip value lookup (per 1.0 standard lot, quoted in USD) ────────────────
const PIP_VALUE_PER_LOT: Record<string, number> = {
  // USD quote pairs → 10 USD per pip per lot
  EURUSD: 10, GBPUSD: 10, AUDUSD: 10, NZDUSD: 10,
  XAUUSD: 10, XAGUSD: 50,
  // USD base pairs → pip value varies with current price (approximated)
  USDJPY: 9.09, USDCAD: 7.69, USDCHF: 10.99,
  // Cross pairs (approximated common values)
  EURJPY: 9.09, GBPJPY: 9.09, AUDJPY: 9.09, CADJPY: 9.09,
  EURGBP: 12.5, EURCAD: 7.7, EURCHF: 10.9,
  GBPAUD: 6.5, GBPCAD: 7.7,
};

const COMMON_PAIRS = [
  "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD",
  "AUDUSD", "NZDUSD", "EURJPY", "GBPJPY", "EURGBP",
  "AUDJPY", "EURJPY", "XAUUSD", "XAGUSD",
  "EURCAD", "EURCHF", "GBPCAD", "CADJPY",
];

// ─── Lot size calculation engine ────────────────────────────────────────────
function calcLotSize(
  equity: number,
  riskPercent: number,
  stopLossPips: number,
  pair: string,
): { lots: number; riskAmount: number; pipValue: number } {
  const pipValue = PIP_VALUE_PER_LOT[pair] ?? 10;
  const riskAmount = (equity * riskPercent) / 100;
  if (stopLossPips <= 0 || pipValue <= 0) return { lots: 0, riskAmount, pipValue };
  const lots = riskAmount / (stopLossPips * pipValue);
  return { lots, riskAmount, pipValue };
}

// ─── Risk budget remaining ───────────────────────────────────────────────────
function calcRemainingRiskBudget(account: Account, snap: RiskSnapshot | null): {
  dailyBudgetPct: number;
  totalBudgetPct: number;
  usablePct: number; // min of both, minus already open risk
} {
  const maxDaily = account.max_daily_dd_percent ?? 4;
  const maxTotal = account.max_total_dd_percent ?? 8;
  const dailyUsed = snap?.daily_dd_percent ?? account.daily_dd_percent ?? 0;
  const totalUsed = snap?.total_dd_percent ?? account.total_dd_percent ?? 0;
  const openRisk = snap?.open_risk_percent ?? account.open_risk_percent ?? 0;

  const dailyBudgetPct = Math.max(0, maxDaily - dailyUsed - openRisk);
  const totalBudgetPct = Math.max(0, maxTotal - totalUsed - openRisk);
  const usablePct = Math.min(dailyBudgetPct, totalBudgetPct);
  return { dailyBudgetPct, totalBudgetPct, usablePct };
}

// ─── Severity color ──────────────────────────────────────────────────────────
function severityColor(sev: "SAFE" | "WARNING" | "CRITICAL" | string): string {
  if (sev === "SAFE") return "#22c55e";
  if (sev === "WARNING") return "#f59e0b";
  return "#ef4444";
}

// ─── Inline style helpers ────────────────────────────────────────────────────
const card: React.CSSProperties = {
  background: "var(--bg-card,#111827)",
  border: "1px solid var(--border,#1e293b)",
  borderRadius: 12,
  padding: "24px",
};
const label: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  letterSpacing: "0.1em",
  color: "var(--text-dim,#475569)",
  fontFamily: "var(--font-mono,'Share Tech Mono',monospace)",
  textTransform: "uppercase" as const,
  marginBottom: 6,
  display: "block",
};
const inputStyle: React.CSSProperties = {
  width: "100%",
  background: "var(--bg-elevated,#1a2332)",
  border: "1px solid var(--border,#1e293b)",
  borderRadius: 8,
  padding: "10px 12px",
  fontSize: 13,
  fontFamily: "var(--font-mono,'Share Tech Mono',monospace)",
  color: "var(--text,#e2e8f0)",
  outline: "none",
  boxSizing: "border-box" as const,
};
const selectStyle: React.CSSProperties = {
  ...inputStyle,
  cursor: "pointer",
  appearance: "none" as const,
  WebkitAppearance: "none" as const,
};
const grid2: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr 1fr",
  gap: 14,
};
const resultRow: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  padding: "10px 0",
  borderBottom: "1px solid var(--border,#1e293b)",
};

// ─── Component ───────────────────────────────────────────────────────────────
export function LotSizeCalculator() {
  const { data: accounts, isLoading: accountsLoading } = useAccounts();
  const { snapshot } = useLiveRisk();

  // Inputs
  const [selectedAccountId, setSelectedAccountId] = useState<string>("");
  const [pair, setPair] = useState("EURUSD");
  const [customPair, setCustomPair] = useState("");
  const [stopLossPips, setStopLossPips] = useState<string>("20");
  const [manualRiskPct, setManualRiskPct] = useState<string>("");
  const [useManualRisk, setUseManualRisk] = useState(false);
  const [accountBase, setAccountBase] = useState<"equity" | "balance">("equity");

  // Auto-select first account
  useEffect(() => {
    if (accounts && accounts.length > 0 && !selectedAccountId) {
      setSelectedAccountId(accounts[0].account_id ?? accounts[0].id ?? "");
    }
  }, [accounts, selectedAccountId]);

  // Selected account
  const selectedAccount = useMemo<Account | null>(() => {
    if (!accounts || !selectedAccountId) return null;
    return accounts.find(
      (a) => a.account_id === selectedAccountId || a.id === selectedAccountId
    ) ?? null;
  }, [accounts, selectedAccountId]);

  // Snap for this account (from live risk hook — assumes single account or first)
  const snap = snapshot as (RiskSnapshot & Record<string, number>) | null;

  // Effective pair
  const effectivePair = customPair.trim().toUpperCase() || pair;

  // Risk budget
  const riskBudget = useMemo(() => {
    if (!selectedAccount) return null;
    return calcRemainingRiskBudget(selectedAccount, snap);
  }, [selectedAccount, snap]);

  // Suggested risk percent from account rules
  const suggestedRiskPct = useMemo(() => {
    if (!selectedAccount || !riskBudget) return 1;
    // Use 50% of remaining daily budget OR 1% max — whichever is lower
    const conservative = Math.min(riskBudget.usablePct * 0.5, 1);
    return Math.max(0.1, parseFloat(conservative.toFixed(2)));
  }, [selectedAccount, riskBudget]);

  const effectiveRiskPct = useManualRisk
    ? parseFloat(manualRiskPct) || suggestedRiskPct
    : suggestedRiskPct;

  // Base capital
  const capitalBase = useMemo(() => {
    if (!selectedAccount) return 0;
    return accountBase === "equity"
      ? (selectedAccount.equity ?? selectedAccount.balance ?? 0)
      : (selectedAccount.balance ?? 0);
  }, [selectedAccount, accountBase]);

  // SL in pips
  const slPips = parseFloat(stopLossPips) || 0;

  // Main calculation
  const calc = useMemo(() => {
    if (!selectedAccount || slPips <= 0 || capitalBase <= 0) return null;
    return calcLotSize(capitalBase, effectiveRiskPct, slPips, effectivePair);
  }, [selectedAccount, slPips, capitalBase, effectiveRiskPct, effectivePair]);

  // Max safe lot (based on remaining risk budget)
  const maxSafeLot = useMemo(() => {
    if (!selectedAccount || !riskBudget || slPips <= 0) return null;
    return calcLotSize(capitalBase, riskBudget.usablePct, slPips, effectivePair).lots;
  }, [selectedAccount, riskBudget, capitalBase, slPips, effectivePair]);

  // Validation
  const validation = useMemo(() => {
    if (!selectedAccount || !riskBudget || !calc) return null;

    const issues: string[] = [];
    let severity: "SAFE" | "WARNING" | "CRITICAL" = "SAFE";

    // Check slots
    const slotsAvail = (selectedAccount.max_concurrent_trades ?? 1) - (selectedAccount.open_trades ?? 0);
    if (slotsAvail <= 0) {
      issues.push("Tidak ada slot trade tersedia");
      severity = "CRITICAL";
    }

    // Check circuit breaker
    if (snap?.circuit_breaker === "OPEN" || snap?.can_trade === false) {
      issues.push("Circuit breaker aktif — trading diblokir");
      severity = "CRITICAL";
    }

    // Check daily DD budget
    if (riskBudget.dailyBudgetPct <= 0) {
      issues.push("Daily drawdown limit tercapai");
      severity = "CRITICAL";
    } else if (effectiveRiskPct > riskBudget.dailyBudgetPct) {
      issues.push(`Risk ${effectiveRiskPct}% melebihi sisa daily budget ${riskBudget.dailyBudgetPct.toFixed(2)}%`);
      severity = severity === "CRITICAL" ? "CRITICAL" : "WARNING";
    }

    // Check total DD budget
    if (riskBudget.totalBudgetPct <= 0) {
      issues.push("Total drawdown limit tercapai");
      severity = "CRITICAL";
    }

    // Risk state from account
    if (selectedAccount.risk_state === "CRITICAL") {
      issues.push("Akun dalam status CRITICAL");
      severity = "CRITICAL";
    } else if (selectedAccount.risk_state === "WARNING" && severity === "SAFE") {
      severity = "WARNING";
    }

    if (issues.length === 0) {
      issues.push("Semua parameter dalam batas aman");
    }

    const canTrade = severity !== "CRITICAL";
    return { issues, severity, canTrade };
  }, [selectedAccount, riskBudget, calc, snap, effectiveRiskPct]);

  const roundLot = (n: number) => Math.floor(n * 100) / 100;

  if (accountsLoading) {
    return (
      <div style={{ ...card, textAlign: "center", padding: "48px 32px" }}>
        <p style={{ fontSize: 12, color: "var(--text-muted,#64748b)", fontFamily: "var(--font-mono,monospace)" }}>
          Memuat data akun…
        </p>
      </div>
    );
  }

  if (!accounts || accounts.length === 0) {
    return (
      <div style={{ ...card, textAlign: "center", padding: "48px 32px" }}>
        <p style={{ fontSize: 12, color: "var(--text-muted,#64748b)", fontFamily: "var(--font-mono,monospace)" }}>
          Tidak ada akun tersedia. Tambahkan akun di halaman Risk terlebih dahulu.
        </p>
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, alignItems: "start" }}>

      {/* ── LEFT: Inputs ──────────────────────────────────────────────── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

        {/* Account Selector */}
        <div style={card}>
          <div style={{ marginBottom: 16 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: "var(--text,#e2e8f0)" }}>
              Pilih Akun Trading
            </span>
          </div>
          <div>
            <span style={label}>Akun</span>
            <select
              value={selectedAccountId}
              onChange={(e) => setSelectedAccountId(e.target.value)}
              style={selectStyle}
            >
              {accounts.map((acc) => (
                <option key={acc.account_id ?? acc.id} value={acc.account_id ?? acc.id}>
                  {acc.account_name ?? acc.label ?? acc.name ?? acc.account_id} — {acc.currency ?? "USD"} {acc.prop_firm ? `[${acc.prop_firm_code ?? "PROP"}]` : ""}
                </option>
              ))}
            </select>
          </div>

          {/* Account Info Card */}
          {selectedAccount && (
            <div style={{ marginTop: 14, background: "var(--bg-elevated,#1a2332)", borderRadius: 8, padding: "12px 14px" }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
                <div>
                  <div style={{ ...label, marginBottom: 3 }}>Balance</div>
                  <div style={{ fontSize: 13, fontWeight: 700, fontFamily: "var(--font-mono,monospace)" }}>
                    ${(selectedAccount.balance ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </div>
                </div>
                <div>
                  <div style={{ ...label, marginBottom: 3 }}>Equity</div>
                  <div style={{ fontSize: 13, fontWeight: 700, fontFamily: "var(--font-mono,monospace)" }}>
                    ${(selectedAccount.equity ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </div>
                </div>
                <div>
                  <div style={{ ...label, marginBottom: 3 }}>Status</div>
                  <div style={{ fontSize: 12, fontWeight: 700, fontFamily: "var(--font-mono,monospace)", color: severityColor(selectedAccount.risk_state ?? "SAFE") }}>
                    {selectedAccount.risk_state ?? "SAFE"}
                  </div>
                </div>
              </div>
              {/* DD progress bars */}
              <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
                {[
                  { key: "Daily DD", used: selectedAccount.daily_dd_percent ?? 0, max: selectedAccount.max_daily_dd_percent ?? 4 },
                  { key: "Total DD", used: selectedAccount.total_dd_percent ?? 0, max: selectedAccount.max_total_dd_percent ?? 8 },
                ].map((item) => (
                  <div key={item.key}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                      <span style={{ fontSize: 10, color: "var(--text-dim,#475569)", fontFamily: "var(--font-mono,monospace)" }}>{item.key}</span>
                      <span style={{ fontSize: 10, fontFamily: "var(--font-mono,monospace)", color: item.used / item.max > 0.8 ? "#ef4444" : item.used / item.max > 0.6 ? "#f59e0b" : "#22c55e" }}>
                        {item.used.toFixed(2)}% / {item.max}%
                      </span>
                    </div>
                    <div style={{ height: 4, background: "var(--bg-card,#111827)", borderRadius: 2, overflow: "hidden" }}>
                      <div style={{ height: "100%", width: `${Math.min((item.used / item.max) * 100, 100)}%`, background: item.used / item.max > 0.8 ? "#ef4444" : item.used / item.max > 0.6 ? "#f59e0b" : "#22c55e", borderRadius: 2, transition: "width 0.3s" }} />
                    </div>
                  </div>
                ))}
              </div>
              {/* Slots */}
              <div style={{ marginTop: 10, display: "flex", gap: 16 }}>
                <div>
                  <span style={{ ...label, marginBottom: 2 }}>Open Trades</span>
                  <span style={{ fontSize: 13, fontWeight: 700, fontFamily: "var(--font-mono,monospace)" }}>
                    {selectedAccount.open_trades ?? 0} / {selectedAccount.max_concurrent_trades ?? 1}
                  </span>
                </div>
                <div>
                  <span style={{ ...label, marginBottom: 2 }}>Open Risk</span>
                  <span style={{ fontSize: 13, fontWeight: 700, fontFamily: "var(--font-mono,monospace)", color: "#f59e0b" }}>
                    {(selectedAccount.open_risk_percent ?? 0).toFixed(2)}%
                  </span>
                </div>
                {riskBudget && (
                  <div>
                    <span style={{ ...label, marginBottom: 2 }}>Sisa Budget</span>
                    <span style={{ fontSize: 13, fontWeight: 700, fontFamily: "var(--font-mono,monospace)", color: riskBudget.usablePct > 1 ? "#22c55e" : riskBudget.usablePct > 0.5 ? "#f59e0b" : "#ef4444" }}>
                      {riskBudget.usablePct.toFixed(2)}%
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Trade Parameters */}
        <div style={card}>
          <div style={{ marginBottom: 16 }}>
            <span style={{ fontSize: 13, fontWeight: 700 }}>Parameter Trade</span>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {/* Pair */}
            <div>
              <span style={label}>Pair</span>
              <div style={{ display: "flex", gap: 8 }}>
                <select value={pair} onChange={(e) => { setPair(e.target.value); setCustomPair(""); }} style={{ ...selectStyle, flex: 1 }}>
                  {COMMON_PAIRS.map((p) => <option key={p} value={p}>{p}</option>)}
                  <option value="OTHER">Lainnya (ketik manual)</option>
                </select>
                {pair === "OTHER" && (
                  <input
                    type="text"
                    placeholder="GBPNZD"
                    value={customPair}
                    onChange={(e) => setCustomPair(e.target.value.toUpperCase())}
                    style={{ ...inputStyle, width: 100 }}
                    maxLength={8}
                  />
                )}
              </div>
            </div>

            {/* Stop Loss */}
            <div>
              <span style={label}>Stop Loss (Pips)</span>
              <input
                type="number"
                value={stopLossPips}
                onChange={(e) => setStopLossPips(e.target.value)}
                placeholder="20"
                min="1"
                max="500"
                style={inputStyle}
              />
            </div>

            {/* Capital Base */}
            <div>
              <span style={label}>Basis Kalkulasi</span>
              <div style={{ display: "flex", gap: 8 }}>
                {(["equity", "balance"] as const).map((opt) => (
                  <button
                    key={opt}
                    onClick={() => setAccountBase(opt)}
                    style={{
                      flex: 1, padding: "8px 12px", fontSize: 11, fontFamily: "var(--font-mono,monospace)",
                      fontWeight: 600, letterSpacing: "0.06em", cursor: "pointer", borderRadius: 8,
                      border: accountBase === opt ? "1px solid var(--accent,#3b82f6)" : "1px solid var(--border,#1e293b)",
                      background: accountBase === opt ? "rgba(59,130,246,0.12)" : "var(--bg-elevated,#1a2332)",
                      color: accountBase === opt ? "var(--accent,#3b82f6)" : "var(--text-muted,#64748b)",
                      transition: "all 0.15s",
                    }}
                  >
                    {opt.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>

            {/* Risk % */}
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                <span style={label}>Risk Per Trade</span>
                <button
                  onClick={() => setUseManualRisk(!useManualRisk)}
                  style={{
                    fontSize: 10, fontFamily: "var(--font-mono,monospace)", fontWeight: 600,
                    padding: "2px 8px", borderRadius: 4, cursor: "pointer",
                    border: "1px solid var(--border,#1e293b)",
                    background: useManualRisk ? "rgba(59,130,246,0.1)" : "transparent",
                    color: useManualRisk ? "var(--accent,#3b82f6)" : "var(--text-dim,#475569)",
                  }}
                >
                  {useManualRisk ? "MANUAL" : "AUTO"}
                </button>
              </div>
              {useManualRisk ? (
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input
                    type="number"
                    value={manualRiskPct}
                    onChange={(e) => setManualRiskPct(e.target.value)}
                    placeholder={suggestedRiskPct.toString()}
                    min="0.01"
                    max="5"
                    step="0.1"
                    style={{ ...inputStyle, flex: 1 }}
                  />
                  <span style={{ fontSize: 13, fontFamily: "var(--font-mono,monospace)", color: "var(--text-muted,#64748b)" }}>%</span>
                </div>
              ) : (
                <div style={{ ...inputStyle, display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "default" }}>
                  <span style={{ fontWeight: 700 }}>{suggestedRiskPct}%</span>
                  <span style={{ fontSize: 10, color: "var(--text-dim,#475569)" }}>
                    auto (dari budget sisa)
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ── RIGHT: Results ────────────────────────────────────────────── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

        {/* Main Result */}
        <div style={{ ...card, borderLeft: `3px solid ${validation ? severityColor(validation.severity) : "var(--border,#1e293b)"}` }}>
          <div style={{ marginBottom: 16 }}>
            <span style={{ fontSize: 13, fontWeight: 700 }}>Hasil Kalkulasi</span>
          </div>

          {!calc || slPips <= 0 ? (
            <div style={{ textAlign: "center", padding: "24px 0" }}>
              <p style={{ fontSize: 12, color: "var(--text-muted,#64748b)", fontFamily: "var(--font-mono,monospace)" }}>
                Masukkan Stop Loss untuk menghitung
              </p>
            </div>
          ) : (
            <>
              {/* BIG LOT SIZE */}
              <div style={{ textAlign: "center", padding: "20px 0", marginBottom: 8 }}>
                <div style={{ fontSize: 10, fontFamily: "var(--font-mono,monospace)", fontWeight: 700, letterSpacing: "0.12em", color: "var(--text-dim,#475569)", marginBottom: 8 }}>
                  RECOMMENDED LOT SIZE
                </div>
                <div style={{ fontSize: 52, fontWeight: 900, fontFamily: "var(--font-mono,'Share Tech Mono',monospace)", lineHeight: 1, color: validation?.canTrade ? "var(--accent,#3b82f6)" : "#ef4444", letterSpacing: "-0.02em" }}>
                  {roundLot(calc.lots).toFixed(2)}
                </div>
                <div style={{ fontSize: 12, color: "var(--text-muted,#64748b)", marginTop: 6, fontFamily: "var(--font-mono,monospace)" }}>
                  lots · {effectivePair}
                </div>
              </div>

              {/* Detail rows */}
              <div style={{ borderTop: "1px solid var(--border,#1e293b)", paddingTop: 14 }}>
                {[
                  { label: "Risk Amount", value: `$${calc.riskAmount.toFixed(2)}` },
                  { label: "Risk %", value: `${effectiveRiskPct.toFixed(2)}%` },
                  { label: "Stop Loss", value: `${slPips} pips` },
                  { label: "Pip Value / Lot", value: `$${calc.pipValue.toFixed(2)}` },
                  { label: "Capital Base", value: `$${capitalBase.toLocaleString("en-US", { maximumFractionDigits: 2 })} (${accountBase})` },
                  { label: "Max Safe Lot", value: maxSafeLot != null ? `${roundLot(maxSafeLot).toFixed(2)} lots` : "—", highlight: true },
                ].map((row, i, arr) => (
                  <div key={row.label} style={{ ...resultRow, borderBottom: i === arr.length - 1 ? "none" : undefined }}>
                    <span style={{ fontSize: 12, color: "var(--text-muted,#64748b)", fontFamily: "var(--font-mono,monospace)" }}>{row.label}</span>
                    <span style={{ fontSize: 13, fontWeight: 700, fontFamily: "var(--font-mono,monospace)", color: row.highlight ? "#f59e0b" : "var(--text,#e2e8f0)" }}>
                      {row.value}
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        {/* Risk Budget Breakdown */}
        {selectedAccount && riskBudget && (
          <div style={card}>
            <div style={{ marginBottom: 14 }}>
              <span style={{ fontSize: 13, fontWeight: 700 }}>Risk Budget Akun</span>
            </div>
            {[
              {
                label: "Daily Budget Tersisa",
                pct: riskBudget.dailyBudgetPct,
                max: selectedAccount.max_daily_dd_percent ?? 4,
                color: riskBudget.dailyBudgetPct > 2 ? "#22c55e" : riskBudget.dailyBudgetPct > 0.5 ? "#f59e0b" : "#ef4444",
              },
              {
                label: "Total Budget Tersisa",
                pct: riskBudget.totalBudgetPct,
                max: selectedAccount.max_total_dd_percent ?? 8,
                color: riskBudget.totalBudgetPct > 4 ? "#22c55e" : riskBudget.totalBudgetPct > 1 ? "#f59e0b" : "#ef4444",
              },
            ].map((item) => (
              <div key={item.label} style={{ marginBottom: 14 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                  <span style={{ fontSize: 11, color: "var(--text-muted,#64748b)", fontFamily: "var(--font-mono,monospace)" }}>{item.label}</span>
                  <span style={{ fontSize: 12, fontWeight: 700, fontFamily: "var(--font-mono,monospace)", color: item.color }}>
                    {item.pct.toFixed(2)}% / {item.max}%
                  </span>
                </div>
                <div style={{ height: 8, background: "var(--bg-elevated,#1a2332)", borderRadius: 4, overflow: "hidden" }}>
                  <div style={{
                    height: "100%",
                    width: `${Math.min((item.pct / item.max) * 100, 100)}%`,
                    background: item.color,
                    borderRadius: 4,
                    transition: "width 0.3s",
                  }} />
                </div>
              </div>
            ))}

            {/* Prop Firm Rules */}
            {selectedAccount.prop_firm && (
              <div style={{ background: "var(--bg-elevated,#1a2332)", borderRadius: 8, padding: "12px 14px", marginTop: 4 }}>
                <div style={{ ...label, color: "#f59e0b", marginBottom: 8 }}>Prop Firm Rules [{selectedAccount.prop_firm_code ?? "PROP"}]</div>
                {[
                  { rule: "Daily DD Limit", val: `${selectedAccount.max_daily_dd_percent ?? 4}%`, ok: (selectedAccount.daily_dd_percent ?? 0) < (selectedAccount.max_daily_dd_percent ?? 4) },
                  { rule: "Total DD Limit", val: `${selectedAccount.max_total_dd_percent ?? 8}%`, ok: (selectedAccount.total_dd_percent ?? 0) < (selectedAccount.max_total_dd_percent ?? 8) },
                  { rule: "Max Concurrent", val: `${selectedAccount.max_concurrent_trades ?? 1} trades`, ok: (selectedAccount.open_trades ?? 0) < (selectedAccount.max_concurrent_trades ?? 1) },
                ].map((item) => (
                  <div key={item.rule} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "4px 0", fontSize: 11, fontFamily: "var(--font-mono,monospace)" }}>
                    <span style={{ color: "var(--text-muted,#64748b)", display: "flex", alignItems: "center", gap: 6 }}>
                      <span style={{ color: item.ok ? "#22c55e" : "#ef4444" }}>{item.ok ? "✓" : "✗"}</span>
                      {item.rule}
                    </span>
                    <span style={{ color: "var(--text,#e2e8f0)", fontWeight: 600 }}>{item.val}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Validation / Status */}
        {validation && (
          <div style={{
            ...card,
            borderLeft: `3px solid ${severityColor(validation.severity)}`,
            background: validation.severity === "SAFE"
              ? "rgba(34,197,94,0.05)"
              : validation.severity === "WARNING"
                ? "rgba(245,158,11,0.05)"
                : "rgba(239,68,68,0.05)",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
              <div style={{ width: 8, height: 8, borderRadius: "50%", background: severityColor(validation.severity), flexShrink: 0 }} />
              <span style={{ fontSize: 12, fontWeight: 700, fontFamily: "var(--font-mono,monospace)", color: severityColor(validation.severity), letterSpacing: "0.08em" }}>
                {validation.severity} — {validation.canTrade ? "TRADE DIIZINKAN" : "TRADE DIBLOKIR"}
              </span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {validation.issues.map((issue, i) => (
                <div key={i} style={{ fontSize: 12, color: "var(--text-muted,#64748b)", display: "flex", gap: 8, alignItems: "flex-start" }}>
                  <span style={{ color: validation.severity === "SAFE" ? "#22c55e" : "#f59e0b", flexShrink: 0 }}>
                    {validation.severity === "SAFE" ? "✓" : "→"}
                  </span>
                  <span>{issue}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
