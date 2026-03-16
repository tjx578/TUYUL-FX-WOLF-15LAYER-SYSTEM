"use client";

// ============================================================
// TUYUL FX Wolf-15 — TakeSignalForm (modal overlay)
// ============================================================

import { useState } from "react";
import type { L12Verdict, Account } from "@/types";
import {
  previewRiskMulti,
  takeSignal,
  skipSignal,
  type RiskPreviewAccountItem,
  type TakeSignalRequest,
} from "@/lib/api";

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
  const [selectedAccountIds, setSelectedAccountIds] = useState<string[]>(
    accounts[0]?.account_id ? [accounts[0].account_id] : []
  );
  const [riskPercent, setRiskPercent] = useState(1.0);
  const [riskMode, setRiskMode] = useState<"FIXED" | "SPLIT">("FIXED");
  const [previews, setPreviews] = useState<RiskPreviewAccountItem[]>([]);
  const [previewing, setPreviewing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isExecutable = verdict.verdict.toString().startsWith("EXECUTE");
  const direction: "BUY" | "SELL" | undefined =
    verdict.direction ??
    (String(verdict.verdict).includes("BUY")
      ? "BUY"
      : String(verdict.verdict).includes("SELL")
        ? "SELL"
        : undefined);
  const [directionError, setDirectionError] = useState<string | null>(
    !direction ? "Signal direction unknown — cannot execute" : null
  );

  function toggleAccount(accountId: string) {
    setSelectedAccountIds((prev) =>
      prev.includes(accountId)
        ? prev.filter((x) => x !== accountId)
        : [...prev, accountId]
    );
  }

  async function handlePreview() {
    if (!selectedAccountIds.length) return;
    setPreviewing(true);
    setError(null);
    try {
      const result = await previewRiskMulti({
        verdict_id: `${verdict.symbol}_${verdict.timestamp}`,
        accounts: selectedAccountIds.map((account_id) => ({ account_id })),
        risk_percent: riskPercent,
        risk_mode: riskMode,
      });
      setPreviews(result.previews ?? []);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to preview risk");
    } finally {
      setPreviewing(false);
    }
  }

  async function handleTake() {
    if (!selectedAccountIds.length) return;
    if (!direction) {
      setError("Signal direction unknown — cannot execute");
      return;
    }

    const rejected = new Set(
      previews.filter((p) => !p.allowed).map((p) => p.account_id)
    );
    const takeAccounts = selectedAccountIds.filter((id) => !rejected.has(id));
    if (!takeAccounts.length) {
      setError("No eligible account selected. Preview and uncheck rejected accounts.");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const req: TakeSignalRequest = {
        verdict_id: `${verdict.symbol}_${verdict.timestamp}`,
        accounts: takeAccounts,
        pair: verdict.symbol,
        direction,
        entry: verdict.entry_price ?? 0,
        sl: verdict.stop_loss ?? 0,
        tp: verdict.take_profit_1 ?? 0,
        risk_percent: riskPercent,
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
          {/* Account multi-select */}
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
              ACCOUNTS
            </label>
            <div
              style={{
                display: "grid",
                gap: 6,
                maxHeight: 132,
                overflowY: "auto",
                padding: 8,
                borderRadius: 6,
                border: "1px solid rgba(255,255,255,0.08)",
                background: "var(--bg-card)",
              }}
            >
              {accounts.map((a) => (
                <label key={a.account_id} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12 }}>
                  <input
                    type="checkbox"
                    checked={selectedAccountIds.includes(a.account_id)}
                    onChange={() => toggleAccount(a.account_id)}
                  />
                  <span>
                    {a.account_name} — {a.broker} (${a.balance.toLocaleString()})
                  </span>
                </label>
              ))}
            </div>
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

          <div style={{ display: "flex", justifyContent: "flex-end" }}>
            <button
              className="btn btn-ghost"
              disabled={previewing || loading || !selectedAccountIds.length}
              onClick={handlePreview}
            >
              {previewing ? "PREVIEWING..." : "PREVIEW RISK"}
            </button>
          </div>

          {previews.length > 0 && (
            <div
              style={{
                border: "1px solid rgba(255,255,255,0.08)",
                borderRadius: 8,
                overflow: "hidden",
              }}
            >
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                <thead style={{ background: "rgba(255,255,255,0.03)", color: "var(--text-muted)" }}>
                  <tr>
                    <th style={{ textAlign: "left", padding: "6px 8px" }}>ACCOUNT</th>
                    <th style={{ textAlign: "right", padding: "6px 8px" }}>LOT</th>
                    <th style={{ textAlign: "right", padding: "6px 8px" }}>DD AFTER</th>
                    <th style={{ textAlign: "right", padding: "6px 8px" }}>STATUS</th>
                  </tr>
                </thead>
                <tbody>
                  {previews.map((p) => (
                    <tr key={p.account_id}>
                      <td style={{ padding: "6px 8px" }}>{p.account_id}</td>
                      <td className="num" style={{ textAlign: "right", padding: "6px 8px" }}>{p.lot_size.toFixed(2)}</td>
                      <td className="num" style={{ textAlign: "right", padding: "6px 8px" }}>{p.daily_dd_after.toFixed(2)}%</td>
                      <td
                        style={{
                          textAlign: "right",
                          padding: "6px 8px",
                          color: p.allowed ? "var(--green)" : "var(--red)",
                          fontWeight: 700,
                        }}
                        title={p.reason ?? ""}
                      >
                        {p.allowed ? "ALLOW" : "REJECT"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

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
      {(error || directionError) && (
        <div
          style={{
            fontSize: 11,
            color: "var(--red)",
            padding: "8px 12px",
            background: "rgba(255,61,87,0.08)",
            borderRadius: 4,
          }}
        >
          {error || directionError}
        </div>
      )}

      {/* Actions */}
      <div style={{ display: "flex", gap: 8 }}>
        {isExecutable && (
          <button
            className="btn btn-take"
            style={{ flex: 1 }}
            disabled={loading || !selectedAccountIds.length || !direction}
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
