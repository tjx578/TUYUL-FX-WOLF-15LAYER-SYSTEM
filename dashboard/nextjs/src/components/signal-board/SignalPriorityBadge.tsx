"use client";

import type { L12Verdict } from "@/types";
import { urgencyScore } from "@/hooks/useSignalBoardState";

interface Props {
  verdict: L12Verdict;
}

export function SignalPriorityBadge({ verdict }: Props) {
  const score = urgencyScore(verdict);
  const tier = score >= 1.5 ? "P1" : score >= 0.8 ? "P2" : "P3";
  const color = tier === "P1" ? "var(--accent)" : tier === "P2" ? "var(--yellow)" : "var(--text-muted)";
  const bg = tier === "P1" ? "var(--accent-muted)" : tier === "P2" ? "var(--yellow-glow)" : "rgba(255,255,255,0.04)";

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        minWidth: 26,
        height: 18,
        borderRadius: 4,
        background: bg,
        border: `1px solid ${color}`,
        fontFamily: "var(--font-mono)",
        fontSize: 9,
        fontWeight: 800,
        color,
        letterSpacing: "0.06em",
        padding: "0 5px",
      }}
      title={`Urgency score: ${score.toFixed(2)}`}
    >
      {tier}
    </span>
  );
}
