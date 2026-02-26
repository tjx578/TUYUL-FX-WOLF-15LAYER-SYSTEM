// ============================================================
// TUYUL FX Wolf-15 — Glass Institutional Panel
// Reusable glass-morphism card with optional glow accent.
// ============================================================

import { ReactNode } from "react";
import clsx from "clsx";

interface PanelProps {
  children: ReactNode;
  className?: string;
  glow?: "cyan" | "emerald" | "orange" | "none";
  onClick?: () => void;
}

export default function Panel({
  children,
  className,
  glow = "none",
  onClick,
}: PanelProps) {
  return (
    <div
      onClick={onClick}
      className={clsx(
        "relative rounded-2xl border border-border-subtle bg-bg-panel backdrop-blur-xl p-6",
        "shadow-[0_20px_60px_rgba(0,0,0,0.6)]",
        glow === "cyan"    && "shadow-glow-cyan",
        glow === "emerald" && "shadow-glow-emerald",
        glow === "orange"  && "shadow-glow-orange",
        className
      )}
    >
      {/* Subtle gradient border lighting */}
      <div className="pointer-events-none absolute inset-0 rounded-2xl border border-transparent bg-gradient-to-br from-white/10 via-transparent to-transparent opacity-40" />

      {children}
    </div>
  );
}
