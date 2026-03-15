"use client";

import { useEffect, useState } from "react";
import type { L12Verdict } from "@/types";
import { VerdictType } from "@/types";
import { SignalPriorityBadge } from "./SignalPriorityBadge";
import { expiryCountdown, gateBlockReason } from "@/hooks/useSignalBoardState";
import { GateStatus } from "@/components/GateStatus";

interface Props {
  verdict: L12Verdict;
  tab: "ELIGIBLE" | "BLOCKED" | "COOLDOWN" | "EXPIRED" | "IGNORED";
  selected: boolean;
  calendarLocked: boolean;
  calendarLockReason?: string;
  onSelect: () => void;
}

export function SignalRowCard({
  verdict,
  tab,
  selected,
  calendarLocked,
  calendarLockReason,
  onSelect,
}: Props) {
  const [countdown, setCountdown] = useState(
    verdict.expires_at ? expiryCountdown(verdict.expires_at) : null
  );

  useEffect(() => {
    if (!verdict.expires_at) return;
    const interval = setInterval(() => {
      setCountdown(expiryCountdown(verdict.expires_at!));
    }, 1000);
    return () => clearInterval(interval);
  }, [verdict.expires_at]);

  const isEligible = tab === "ELIGIBLE";
  const isBlocked = tab === "BLOCKED";
  const isBuy =
    verdict.direction === "BUY" ||
    verdict.verdict === VerdictType.EXECUTE_BUY;

  const directionColor = isBuy ? "var(--green)" : "var(--red)";
  const directionLabel = isBuy ? "BUY" : "SELL";

  const blockReason = calendarLocked
    ? calendarLockReason ?? "NEWS LOCK"
    : gateBlockReason(verdict);

  const failedGates = verdict.gates?.filter((g) => !g.passed) ?? [];

  return (
    <button
      onClick={onSelect}
      style={{
        display: "block",
        width: "100%",
        textAlign: "left",
        padding: "12px 14px",
        borderRadius: "var(--radius-md)",
        background: selected ? "rgba(26,110,255,0.10)" : "var(--bg-card)",
        border: `1px solid ${selected ? "var(--accent)" : "var(--border-default)"}`,
        cursor: "pointer",
        transition: "border-color 0.12s, background 0.12s",
        opacity: tab === "EXPIRED" || tab === "IGNORED" ? 0.55 : 1,
      }}
    >
      {/* Row 1: symbol + badges + direction + countdown */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <span
          style={{
            fontFamily: "var(--font-display)",
            fontSize: 14,
            fontWeight: 700,
            color: "var(--text-primary)",
            letterSpacing: "0.04em",
          }}
        >
          {verdict.symbol}
        </span>

        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            fontWeight: 700,
            color: directionColor,
            background: `${directionColor}18`,
            border: `1px solid ${directionColor}40`,
            borderRadius: 4,
            padding: "1px 6px",
          }}
        >
          {directionLabel}
        </span>

        <SignalPriorityBadge verdict={verdict} />

        {/* gate dots compact */}
        {verdict.gates?.length > 0 && (
          <GateStatus gates={verdict.gates} compact />
        )}

        {/* expiry countdown */}
        {countdown && (
          <span
            style={{
              marginLeft: "auto",
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              color: countdown === "EXPIRED" ? "var(--red)" : "var(--yellow)",
            }}
          >
            {countdown}
          </span>
        )}
      </div>

      {/* Row 2: entry / sl / tp / rr / conf */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        {[
          { label: "CONF", value: `${((verdict.confidence ?? 0) * 100).toFixed(0)}%`, color: isEligible ? "var(--text-primary)" : "var(--text-muted)" },
          { label: "ENTRY", value: verdict.entry_price?.toFixed(5) ?? "—" },
          { label: "SL", value: verdict.stop_loss?.toFixed(5) ?? "—" },
          { label: "TP", value: verdict.take_profit_1?.toFixed(5) ?? "—" },
          { label: "RR", value: verdict.risk_reward_ratio ? `1:${verdict.risk_reward_ratio.toFixed(1)}` : "—" },
        ].map(({ label, value, color }) => (
          <div key={label} style={{ display: "flex", flexDirection: "column", gap: 1 }}>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 8, color: "var(--text-faint)", letterSpacing: "0.1em" }}>
              {label}
            </span>
            <span
              className="num"
              style={{ fontSize: 11, color: color ?? "var(--text-secondary)" }}
            >
              {value}
            </span>
          </div>
        ))}
      </div>

      {/* Row 3: blocked reason inline */}
      {isBlocked && blockReason && (
        <div
          style={{
            marginTop: 8,
            padding: "5px 8px",
            borderRadius: 4,
            background: "rgba(255,61,87,0.07)",
            border: "1px solid rgba(255,61,87,0.18)",
            fontSize: 10,
            color: "var(--red)",
            fontFamily: "var(--font-mono)",
          }}
        >
          {calendarLocked ? "NEWS LOCK" : `GATE FAIL`}: {blockReason}
        </div>
      )}

      {/* failed gate count for non-eligible */}
      {isBlocked && !calendarLocked && failedGates.length > 0 && (
        <div
          style={{
            marginTop: 6,
            display: "flex",
            gap: 4,
            flexWrap: "wrap",
          }}
        >
          {failedGates.map((g) => (
            <span
              key={g.gate_id}
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 9,
                color: "var(--red)",
                background: "rgba(255,61,87,0.06)",
                border: "1px solid rgba(255,61,87,0.14)",
                borderRadius: 3,
                padding: "1px 5px",
              }}
            >
              {g.name ?? g.gate_id}
            </span>
          ))}
        </div>
      )}
    </button>
  );
}
