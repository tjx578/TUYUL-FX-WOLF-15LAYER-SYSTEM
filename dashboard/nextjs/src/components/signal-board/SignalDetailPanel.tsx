"use client";

// ============================================================
// SignalDetailPanel — gate rationale + risk preview + action bar
// ============================================================

import { useState } from "react";
import type { L12Verdict, Account } from "@/types";
import { VerdictType } from "@/types";
import { GateStatus } from "@/components/GateStatus";
import { BlockedReasonBanner } from "./BlockedReasonBanner";
import { gateBlockReason } from "@/hooks/useSignalBoardState";
import {
  takeSignal,
  skipSignal,
  type RiskPreviewAccountItem,
} from "@/lib/api";

interface Props {
  signal: L12Verdict;
  accounts: Account[];
  riskPreviews: RiskPreviewAccountItem[];
  riskPreviewLoading: boolean;
  riskPreviewError: string | null;
  calendarLocked: boolean;
  calendarLockReason?: string;
  onRunPreview: (accountIds: string[], riskPercent: number, riskMode: "FIXED" | "SPLIT") => void;
  onDone: () => void;
  onClose: () => void;
}

export function SignalDetailPanel({
  signal,
  accounts,
  riskPreviews,
  riskPreviewLoading,
  riskPreviewError,
  calendarLocked,
  calendarLockReason,
  onRunPreview,
  onDone,
  onClose,
}: Props) {
  const [selectedAccountIds, setSelectedAccountIds] = useState<string[]>(
    accounts[0]?.account_id ? [accounts[0].account_id] : []
  );
  const [riskPercent, setRiskPercent] = useState(1.0);
  const [riskMode, setRiskMode] = useState<"FIXED" | "SPLIT">("FIXED");
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const isExecute =
    String(signal.verdict).startsWith("EXECUTE");
  const isBuy =
    signal.direction === "BUY" || signal.verdict === VerdictType.EXECUTE_BUY;
  const dirColor = isBuy ? "var(--green)" : "var(--red)";
  const blockReason = calendarLocked
    ? calendarLockReason ?? "High-impact news lock"
    : gateBlockReason(signal);
  const isBlocked = calendarLocked || (signal.gates?.some((g) => !g.passed) ?? false);
  const previewDone = riskPreviews.length > 0;
  const allRejected = previewDone && riskPreviews.every((p) => !p.allowed);
  const canTake = isExecute && !isBlocked && previewDone && !allRejected;

  function toggleAccount(id: string) {
    setSelectedAccountIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  }

  async function handleTake() {
    const eligible = riskPreviews
      .filter((p) => p.allowed)
      .map((p) => p.account_id);
    if (!eligible.length) return;
    setActionLoading(true);
    setActionError(null);
    try {
      await takeSignal({
        verdict_id: `${signal.symbol}_${signal.timestamp}`,
        accounts: eligible,
        pair: signal.symbol,
        direction: isBuy ? "BUY" : "SELL",
        entry: signal.entry_price ?? 0,
        sl: signal.stop_loss ?? 0,
        tp: signal.take_profit_1 ?? 0,
        risk_percent: riskPercent,
      });
      onDone();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Take failed");
    } finally {
      setActionLoading(false);
    }
  }

  async function handleSkip() {
    setActionLoading(true);
    setActionError(null);
    try {
      await skipSignal({
        signal_id: `${signal.symbol}_${signal.timestamp}`,
        pair: signal.symbol,
        reason: "Manual skip from Signal Board",
      });
      onDone();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Skip failed");
    } finally {
      setActionLoading(false);
    }
  }

  const label = (l: string) => (
    <div
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 9,
        letterSpacing: "0.1em",
        color: "var(--text-faint)",
        marginBottom: 2,
      }}
    >
      {l}
    </div>
  );

  return (
    <div
      className="panel"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 14,
        padding: 18,
        position: "sticky",
        top: 24,
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div>
          <div
            style={{
              fontFamily: "var(--font-display)",
              fontSize: 16,
              fontWeight: 700,
              color: "var(--text-primary)",
              letterSpacing: "0.05em",
            }}
          >
            {signal.symbol}
          </div>
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              color: dirColor,
              marginTop: 1,
            }}
          >
            {isBuy ? "BUY" : "SELL"} — {String(signal.verdict)}
          </div>
        </div>
        <button
          onClick={onClose}
          style={{
            marginLeft: "auto",
            background: "none",
            border: "none",
            color: "var(--text-muted)",
            fontSize: 16,
            cursor: "pointer",
            padding: 4,
          }}
          aria-label="Close detail panel"
        >
          ×
        </button>
      </div>

      {/* Signal metrics grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}>
        {[
          { l: "CONF", v: `${((signal.confidence ?? 0) * 100).toFixed(1)}%` },
          { l: "ENTRY", v: signal.entry_price?.toFixed(5) ?? "—" },
          { l: "SL", v: signal.stop_loss?.toFixed(5) ?? "—" },
          { l: "TP1", v: signal.take_profit_1?.toFixed(5) ?? "—" },
          { l: "TP2", v: signal.take_profit_2?.toFixed(5) ?? "—" },
          { l: "R:R", v: signal.risk_reward_ratio ? `1:${signal.risk_reward_ratio.toFixed(2)}` : "—" },
        ].map(({ l, v }) => (
          <div key={l} className="card" style={{ padding: "7px 10px" }}>
            {label(l)}
            <div className="num" style={{ fontSize: 12, color: "var(--text-primary)" }}>{v}</div>
          </div>
        ))}
      </div>

      {/* L12 scores */}
      {signal.scores && (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {[
            { l: "WOLF", v: signal.scores.wolf_score },
            { l: "TII", v: signal.scores.tii_score },
            { l: "FRPC", v: signal.scores.frpc_score },
          ].map(({ l, v }) => (
            <div key={l} style={{ flex: 1, minWidth: 60 }} className="card">
              <div style={{ padding: "6px 8px" }}>
                {label(l)}
                <div
                  className="num"
                  style={{
                    fontSize: 13,
                    color: v >= 0.7 ? "var(--green)" : v >= 0.5 ? "var(--yellow)" : "var(--red)",
                  }}
                >
                  {(v * 100).toFixed(0)}
                </div>
              </div>
            </div>
          ))}
          {signal.scores.regime && (
            <div className="card" style={{ padding: "6px 8px", flex: 1, minWidth: 60 }}>
              {label("REGIME")}
              <div style={{ fontSize: 10, color: "var(--text-secondary)" }}>
                {signal.scores.regime}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Blocked reason */}
      {isBlocked && blockReason && (
        <BlockedReasonBanner reason={blockReason} isNewsLock={calendarLocked} />
      )}

      {/* Gate checks */}
      {signal.gates?.length > 0 && (
        <div className="card" style={{ padding: 12 }}>
          <GateStatus gates={signal.gates} />
        </div>
      )}

      {/* Risk preview — only if eligible */}
      {isExecute && !isBlocked && (
        <>
          <div
            style={{
              borderTop: "1px solid var(--border-subtle)",
              paddingTop: 12,
              display: "flex",
              flexDirection: "column",
              gap: 10,
            }}
          >
            {/* Account selector */}
            <div>
              {label("ACCOUNTS")}
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 6,
                  maxHeight: 100,
                  overflowY: "auto",
                  padding: 8,
                  borderRadius: 6,
                  border: "1px solid rgba(255,255,255,0.07)",
                  background: "var(--bg-elevated)",
                }}
              >
                {accounts.map((a) => (
                  <label
                    key={a.account_id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      fontSize: 11,
                      color: "var(--text-secondary)",
                      cursor: "pointer",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={selectedAccountIds.includes(a.account_id)}
                      onChange={() => toggleAccount(a.account_id)}
                    />
                    {a.account_name} — {a.broker}
                    <span style={{ marginLeft: "auto", fontFamily: "var(--font-mono)", fontSize: 10 }}>
                      ${a.balance.toLocaleString()}
                    </span>
                  </label>
                ))}
              </div>
            </div>

            {/* Risk controls */}
            <div style={{ display: "flex", gap: 8 }}>
              <div style={{ flex: 1 }}>
                {label("RISK %")}
                <input
                  type="number"
                  min={0.1}
                  max={5}
                  step={0.1}
                  value={riskPercent}
                  onChange={(e) => setRiskPercent(parseFloat(e.target.value) || 0)}
                  style={{ width: "100%" }}
                />
              </div>
              <div style={{ flex: 1 }}>
                {label("MODE")}
                <select
                  value={riskMode}
                  onChange={(e) => setRiskMode(e.target.value as "FIXED" | "SPLIT")}
                  style={{ width: "100%" }}
                >
                  <option value="FIXED">FIXED</option>
                  <option value="SPLIT">SPLIT</option>
                </select>
              </div>
              <div style={{ display: "flex", alignItems: "flex-end" }}>
                <button
                  className="btn btn-ghost"
                  style={{ fontSize: 10, padding: "5px 10px", whiteSpace: "nowrap" }}
                  disabled={riskPreviewLoading || !selectedAccountIds.length}
                  onClick={() => onRunPreview(selectedAccountIds, riskPercent, riskMode)}
                >
                  {riskPreviewLoading ? "..." : "PREVIEW"}
                </button>
              </div>
            </div>

            {/* Preview error */}
            {riskPreviewError && (
              <div style={{ fontSize: 10, color: "var(--red)", fontFamily: "var(--font-mono)" }}>
                {riskPreviewError}
              </div>
            )}

            {/* Preview results table */}
            {previewDone && (
              <div
                style={{
                  borderRadius: 6,
                  border: "1px solid rgba(255,255,255,0.07)",
                  overflow: "hidden",
                }}
              >
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 10 }}>
                  <thead>
                    <tr style={{ background: "rgba(255,255,255,0.03)" }}>
                      {["ACCOUNT", "LOT", "DD AFTER", "STATUS"].map((h) => (
                        <th
                          key={h}
                          style={{
                            padding: "5px 8px",
                            textAlign: h === "ACCOUNT" ? "left" : "right",
                            fontFamily: "var(--font-mono)",
                            fontSize: 8,
                            letterSpacing: "0.1em",
                            color: "var(--text-muted)",
                            fontWeight: 600,
                          }}
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {riskPreviews.map((p) => (
                      <tr
                        key={p.account_id}
                        style={{
                          borderTop: "1px solid rgba(255,255,255,0.04)",
                          opacity: p.allowed ? 1 : 0.6,
                        }}
                      >
                        <td style={{ padding: "5px 8px", fontSize: 10, color: "var(--text-secondary)" }}>
                          {p.account_id}
                        </td>
                        <td className="num" style={{ textAlign: "right", padding: "5px 8px" }}>
                          {p.lot_size?.toFixed(2) ?? "—"}
                        </td>
                        <td className="num" style={{ textAlign: "right", padding: "5px 8px" }}>
                          {p.daily_dd_after?.toFixed(2) ?? "—"}%
                        </td>
                        <td
                          style={{
                            textAlign: "right",
                            padding: "5px 8px",
                            fontFamily: "var(--font-mono)",
                            fontSize: 9,
                            fontWeight: 700,
                            color: p.allowed ? "var(--green)" : "var(--red)",
                          }}
                        >
                          {p.allowed ? "ALLOW" : "REJECT"}
                          {p.reason && !p.allowed && (
                            <div style={{ fontSize: 8, color: "var(--text-muted)", fontWeight: 400, maxWidth: 80, textAlign: "right" }}>
                              {p.reason}
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}

      {/* Action error */}
      {actionError && (
        <div
          style={{
            fontSize: 11,
            color: "var(--red)",
            padding: "7px 10px",
            background: "rgba(255,61,87,0.07)",
            borderRadius: 4,
          }}
        >
          {actionError}
        </div>
      )}

      {/* Action bar */}
      <div style={{ display: "flex", gap: 8, paddingTop: 2 }}>
        {isExecute && !isBlocked && (
          <button
            className="btn btn-take"
            style={{ flex: 1 }}
            disabled={actionLoading || !canTake}
            title={!previewDone ? "Run risk preview first" : allRejected ? "All accounts rejected" : ""}
            onClick={handleTake}
          >
            {actionLoading ? "PROCESSING..." : !previewDone ? "PREVIEW FIRST" : "CONFIRM TAKE"}
          </button>
        )}
        <button
          className="btn btn-skip"
          style={{ flex: 1 }}
          disabled={actionLoading}
          onClick={handleSkip}
        >
          SKIP
        </button>
        <button className="btn btn-ghost" onClick={onClose} disabled={actionLoading}>
          CANCEL
        </button>
      </div>
    </div>
  );
}
