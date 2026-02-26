"use client";

// ============================================================
// TUYUL FX Wolf-15 — TakeSignalForm (modal overlay)
// ============================================================

import { useState } from "react";
import type { L12Verdict, Account } from "@/types";
import { takeSignal, skipSignal, type TakeSignalRequest } from "@/lib/api";

interface TakeSignalFormProps {
  verdict: L12Verdict;
  accounts: Account[];
  onDone: () => void;
  onCancel: () => void;
}

export function TakeSignalForm({
  verdict,
  accounts,
  onDone,
  onCancel,
}: TakeSignalFormProps) {
  const [accountId, setAccountId] = useState(accounts[0]?.account_id ?? "");
  const [riskPercent, setRiskPercent] = useState(1.0);
  const [riskMode, setRiskMode] = useState<"FIXED" | "SPLIT">("FIXED");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isExecutable = verdict.verdict.toString().startsWith("EXECUTE");
  const direction = verdict.direction ?? (verdict.verdict === "EXECUTE_BUY" ? "BUY" : "SELL") as "BUY" | "SELL";

  async function handleTake() {
    if (!accountId) return;
    setLoading(true);
    setError(null);
    try {
      const req: TakeSignalRequest = {
        signal_id: `${verdict.symbol}_${verdict.timestamp}`,
        account_id: accountId,
        pair: verdict.symbol,
        direction,
        entry: verdict.entry_price ?? 0,
        sl: verdict.stop_loss ?? 0,
        tp: verdict.take_profit_1 ?? 0,
        risk_percent: riskPercent,
        risk_mode: riskMode,
      };
      await takeSignal(req);
      onDone();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to take signal");
    } finally {
      setLoading(false);
    }
  }

  async function handleSkip() {
    setLoading(true);
    try {
      await skipSignal({
        signal_id: `${verdict.symbol}_${verdict.timestamp}`,
        pair: verdict.symbol,
        reason: "Manual skip from dashboard",
      });
      onDone();
    } catch {
      setError("Failed to skip signal");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className="panel animate-fade-in"
      style={{
        width: 420,
        padding: 24,
        display: "flex",
        flexDirection: "column",
        gap: 16,
      }}
    >
      {/* Header */}
      <div>
        <div
          style={{
            fontSize: 14,
            fontWeight: 700,
            letterSpacing: "0.06em",
            color: "var(--accent)",
          }}
        >
          {isExecutable ? "TAKE SIGNAL" : "SIGNAL DETAILS"}
        </div>
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
          {verdict.symbol} — {verdict.verdict}
        </div>
      </div>

      {/* Signal summary */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 8,
        }}
      >
        {[
          { label: "ENTRY", value: verdict.entry_price?.toFixed(5) ?? "—" },
          { label: "SL", value: verdict.stop_loss?.toFixed(5) ?? "—" },
          { label: "TP", value: verdict.take_profit_1?.toFixed(5) ?? "—" },
        ].map(({ label, value }) => (
          <div
            key={label}
            className="card"
            style={{ padding: "8px 10px" }}
          >
            <div style={{ fontSize: 9, color: "var(--text-muted)", letterSpacing: "0.08em" }}>
              {label}
            </div>
            <div className="num" style={{ fontSize: 13, color: "var(--text-primary)" }}>
              {value}
            </div>
          </div>
        ))}
      </div>

      {isExecutable && (
        <>
          {/* Account select */}
          <div>
            <label
              style={{
                display: "block",
                fontSize: 10,
                fontWeight: 600,
                color: "var(--text-muted)",
                letterSpacing: "0.08em",
                marginBottom: 4,
              }}
            >
              ACCOUNT
            </label>
            <select
              value={accountId}
              onChange={(e) => setAccountId(e.target.value)}
              style={{ width: "100%" }}
            >
              {accounts.map((a) => (
                <option key={a.account_id} value={a.account_id}>
                  {a.account_name} — {a.broker} (${a.balance.toLocaleString()})
                </option>
              ))}
            </select>
          </div>

          {/* Risk controls */}
          <div style={{ display: "flex", gap: 12 }}>
            <div style={{ flex: 1 }}>
              <label
                style={{
                  display: "block",
                  fontSize: 10,
                  fontWeight: 600,
                  color: "var(--text-muted)",
                  letterSpacing: "0.08em",
                  marginBottom: 4,
                }}
              >
                RISK %
              </label>
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
              <label
                style={{
                  display: "block",
                  fontSize: 10,
                  fontWeight: 600,
                  color: "var(--text-muted)",
                  letterSpacing: "0.08em",
                  marginBottom: 4,
                }}
              >
                MODE
              </label>
              <select
                value={riskMode}
                onChange={(e) => setRiskMode(e.target.value as "FIXED" | "SPLIT")}
                style={{ width: "100%" }}
              >
                <option value="FIXED">FIXED</option>
                <option value="SPLIT">SPLIT</option>
              </select>
            </div>
          </div>

          {/* RR display */}
          {verdict.risk_reward_ratio && (
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: 12,
                padding: "8px 12px",
                background: "var(--bg-card)",
                borderRadius: 4,
              }}
            >
              <span style={{ color: "var(--text-muted)" }}>R:R</span>
              <span
                className="num"
                style={{
                  color:
                    verdict.risk_reward_ratio >= 2
                      ? "var(--green)"
                      : "var(--yellow)",
                  fontWeight: 700,
                }}
              >
                1:{verdict.risk_reward_ratio.toFixed(2)}
              </span>
            </div>
          )}
        </>
      )}

      {/* Error */}
      {error && (
        <div
          style={{
            fontSize: 11,
            color: "var(--red)",
            padding: "8px 12px",
            background: "rgba(255,61,87,0.08)",
            borderRadius: 4,
          }}
        >
          {error}
        </div>
      )}

      {/* Actions */}
      <div style={{ display: "flex", gap: 8 }}>
        {isExecutable && (
          <button
            className="btn btn-take"
            style={{ flex: 1 }}
            disabled={loading || !accountId}
            onClick={handleTake}
          >
            {loading ? "PROCESSING..." : "▶ CONFIRM TAKE"}
          </button>
        )}
        <button
          className="btn btn-skip"
          style={{ flex: isExecutable ? 0 : 1, minWidth: 100 }}
          disabled={loading}
          onClick={handleSkip}
        >
          ✕ SKIP
        </button>
        <button
          className="btn btn-ghost"
          style={{ minWidth: 80 }}
          onClick={onCancel}
        >
          CANCEL
        </button>
      </div>
    </div>
  );
}
