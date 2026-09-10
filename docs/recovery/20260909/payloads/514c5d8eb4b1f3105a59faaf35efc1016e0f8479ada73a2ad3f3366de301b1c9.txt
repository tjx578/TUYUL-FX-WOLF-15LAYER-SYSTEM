"use client";

import { useEffect, useState } from "react";

interface Props {
  cooldownUntil?: number; // unix timestamp seconds
  symbol: string;
}

export function CooldownPanel({ cooldownUntil, symbol }: Props) {
  const [remaining, setRemaining] = useState<string>("—");

  useEffect(() => {
    if (!cooldownUntil) return;
    const tick = () => {
      const diff = cooldownUntil - Math.floor(Date.now() / 1000);
      if (diff <= 0) {
        setRemaining("READY");
        return;
      }
      const m = Math.floor(diff / 60);
      const s = diff % 60;
      setRemaining(`${m}:${s.toString().padStart(2, "0")}`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [cooldownUntil]);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "10px 14px",
        borderRadius: "var(--radius-md)",
        background: "rgba(255,215,64,0.07)",
        border: "1px solid rgba(255,215,64,0.22)",
      }}
    >
      <div
        style={{
          width: 8,
          height: 8,
          borderRadius: "50%",
          background: "var(--yellow)",
          boxShadow: "0 0 6px var(--yellow)",
          flexShrink: 0,
          animation: "pulse 1.5s ease infinite",
        }}
      />
      <div>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: "0.12em",
            color: "var(--yellow)",
            marginBottom: 2,
          }}
        >
          COOLDOWN — {symbol}
        </div>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 13,
            color: "var(--text-primary)",
          }}
        >
          {remaining}
        </div>
      </div>
    </div>
  );
}
