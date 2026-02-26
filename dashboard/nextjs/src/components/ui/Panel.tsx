// ============================================================
// TUYUL FX Wolf-15 — Glass Institutional Panel
// Reusable glass-morphism card with optional glow accent.
// Includes Hover Glow Engine + Elevation Transition Engine.
// ============================================================

import { ReactNode } from "react";
import clsx from "clsx";

interface PanelProps {
  children: ReactNode;
  className?: string;
  /** Static glow applied permanently */
  glow?: "cyan" | "emerald" | "orange" | "none";
  /** Hover glow variant — activates on mouse-over */
  hoverGlow?: "cyan" | "emerald" | "orange" | "none";
  /** Enable lift + transition on hover */
  interactive?: boolean;
  onClick?: () => void;
}

export default function Panel({
  children,
  className,
  glow = "none",
  hoverGlow = "none",
  interactive = false,
  onClick,
}: PanelProps) {
  return (
    <div
      onClick={onClick}
      className={clsx(
        "relative rounded-2xl border border-border-subtle bg-bg-panel backdrop-blur-xl p-6",
        "shadow-[0_20px_60px_rgba(0,0,0,0.6)]",
        // Static glow
        glow === "cyan"    && "shadow-glow-cyan",
        glow === "emerald" && "shadow-glow-emerald",
        glow === "orange"  && "shadow-glow-orange",
        // Hover glow engine
        hoverGlow !== "none" && "interactive panel-transition",
        hoverGlow === "cyan"    && "glow-hover-cyan",
        hoverGlow === "emerald" && "glow-hover-emerald",
        hoverGlow === "orange"  && "glow-hover-orange",
        // Elevation engine (plain hover lift without glow)
        interactive && hoverGlow === "none" && "interactive panel-transition",
        className
      )}
    >
      {/* Subtle gradient border lighting */}
      <div className="pointer-events-none absolute inset-0 rounded-2xl border border-transparent bg-gradient-to-br from-white/10 via-transparent to-transparent opacity-40" />

      {children}
    </div>
  );
}
