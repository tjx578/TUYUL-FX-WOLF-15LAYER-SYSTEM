"use client";

// ============================================================
// TUYUL FX Wolf-15 — Production Header
// Shows: live execution state, context session/regime,
//        role badge, timezone, last-updated timestamp
// ============================================================

import { useAuthStore } from "@/store/useAuthStore";
import { useExecution, useContext } from "@/lib/api";
import { TimezoneDisplay } from "@/components/TimezoneDisplay";
import { useSessionLabel } from "@/hooks/useSessionLabel";

const EXECUTION_COLORS: Record<string, string> = {
  IDLE: "var(--text-muted)",
  SCANNING: "var(--blue)",
  SIGNAL_READY: "var(--accent)",
  EXECUTING: "var(--green)",
  COOLDOWN: "var(--yellow)",
};

const ROLE_COLORS: Record<string, string> = {
  viewer: "var(--text-muted)",
  operator: "var(--blue)",
  risk_admin: "var(--yellow)",
  config_admin: "var(--accent)",
  approver: "var(--green)",
};

function ExecPip({ state }: { state?: string }) {
  const color = EXECUTION_COLORS[state ?? ""] ?? "var(--text-muted)";
  const isActive = state === "EXECUTING" || state === "SIGNAL_READY";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: color,
          flexShrink: 0,
          display: "inline-block",
          animation: isActive ? "pulse-dot 1.2s ease-in-out infinite" : "none",
        }}
      />
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color, fontWeight: 700, letterSpacing: "0.07em" }}>
        {state ?? "—"}
      </span>
    </div>
  );
}

export default function Header() {
  const user = useAuthStore((state) => state.user);
  const { data: execution } = useExecution();
  const { data: context } = useContext();
  const liveSession = useSessionLabel();

  const roleColor = ROLE_COLORS[user?.role ?? "viewer"] ?? "var(--text-muted)";

  return (
    <header
      className="mb-5"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 16,
        padding: "10px 18px",
        background: "var(--bg-panel)",
        border: "1px solid var(--border-default)",
        borderRadius: "var(--radius-lg)",
        flexWrap: "wrap",
      }}
      aria-label="Dashboard header"
    >
      {/* ── Engine state ── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <div style={{ fontSize: 9, color: "var(--text-muted)", letterSpacing: "0.10em", fontWeight: 700 }}>
          ENGINE
        </div>
        <ExecPip state={execution?.state} />
      </div>

      <div style={{ width: 1, height: 28, background: "var(--border-default)", flexShrink: 0 }} aria-hidden="true" />

      {/* ── Market context ── */}
      <div style={{ display: "flex", gap: 16 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <div style={{ fontSize: 9, color: "var(--text-muted)", letterSpacing: "0.10em", fontWeight: 700 }}>SESSION</div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--cyan)", fontWeight: 700 }}>
            {liveSession}
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <div style={{ fontSize: 9, color: "var(--text-muted)", letterSpacing: "0.10em", fontWeight: 700 }}>REGIME</div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-secondary)", fontWeight: 700 }}>
            {context?.regime ?? "—"}
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <div style={{ fontSize: 9, color: "var(--text-muted)", letterSpacing: "0.10em", fontWeight: 700 }}>ACTIVE PAIRS</div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-secondary)", fontWeight: 700 }}>
            {context?.active_pairs?.length ?? "—"}
          </div>
        </div>
      </div>

      {/* ── Spacer ── */}
      <div style={{ flex: 1 }} />

      {/* ── Timezone ── */}
      <TimezoneDisplay />

      <div style={{ width: 1, height: 28, background: "var(--border-default)", flexShrink: 0 }} aria-hidden="true" />

      {/* ── User info ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 1, alignItems: "flex-end" }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-primary)", maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {user?.email ?? "Unknown"}
          </div>
          <span
            className="badge badge-muted"
            style={{ fontSize: 9, color: roleColor, borderColor: roleColor + "30" }}
          >
            {(user?.role ?? "viewer").toUpperCase()}
          </span>
        </div>
      </div>
    </header>
  );
}
