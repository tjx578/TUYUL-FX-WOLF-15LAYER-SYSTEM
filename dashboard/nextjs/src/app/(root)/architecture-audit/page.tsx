"use client";

// ============================================================
// TUYUL FX Wolf-15 — Architecture Audit Page
// Analisis integrasi script PDF vs kondisi aktual repo
// Script: Python ReportLab PDF generator (WOLF 15-LAYER analysis)
// ============================================================

import { useState } from "react";

// ── Types ─────────────────────────────────────────────────────

type Status = "VERIFIED" | "PARTIAL" | "GAP" | "EXCEEDS";

interface CheckItem {
  claim: string;
  actual: string;
  file?: string;
  status: Status;
}

interface Dimension {
  id: string;
  label: string;
  pdfScore: number;
  institutionalGrade: number;
  items: CheckItem[];
}

// ── Data: script claims vs repo actuals ─────────────────────

const DIMENSIONS: Dimension[] = [
  {
    id: "websocket",
    label: "WebSocket Architecture",
    pdfScore: 9.0,
    institutionalGrade: 9.5,
    items: [
      {
        claim: "7 dedicated WS endpoints (/ws/prices, /ws/trades, /ws/candles, /ws/verdict, /ws/signals, /ws/pipeline, /ws/live)",
        actual: "lib/websocket.ts mendefinisikan: /ws/prices, /ws/trades, /ws/candles, /ws/risk, /ws/equity, /ws/alerts — 6 channel typed hooks. wsService.ts menggunakan NEXT_PUBLIC_WS_URL tunggal (/ws/live). Endpoint /ws/verdict, /ws/signals, /ws/pipeline belum ada di FE hooks.",
        file: "lib/websocket.ts + services/wsService.ts",
        status: "PARTIAL",
      },
      {
        claim: "JWT pre-auth sebelum WS connection diterima",
        actual: "useWolfWebSocket() membaca token via getToken() lalu append ?token=... ke URL. Terverifikasi di websocket.ts baris 64-67.",
        file: "lib/websocket.ts",
        status: "VERIFIED",
      },
      {
        claim: "Ring buffer 100 messages per client untuk disconnect recovery",
        actual: "Ring buffer ada di BACKEND (Python). FE tidak mengimplementasikan client-side ring buffer. wsService.ts tidak memiliki sequence tracking atau replay logic.",
        file: "services/wsService.ts",
        status: "PARTIAL",
      },
      {
        claim: "Exponential backoff reconnect, leader election (Finnhub)",
        actual: "useWolfWebSocket() memiliki RECONNECT_DELAY_MS=3000 fixed (bukan exponential). MAX_RECONNECT_ATTEMPTS=10. Leader election ada di backend service, tidak di FE.",
        file: "lib/websocket.ts",
        status: "PARTIAL",
      },
      {
        claim: "Per-message deflate compression",
        actual: "Tidak diimplementasikan di FE. wsService.ts dan websocket.ts tidak menggunakan WebSocket.perMessageDeflate atau compression options.",
        status: "GAP",
      },
      {
        claim: "SSE sebagai intermediate fallback",
        actual: "Tidak ada SSE implementation. Fallback hanya: WS gagal → mode DEGRADED (setMode). Tidak ada REST polling fallback setelah 30s.",
        file: "hooks/useLivePipeline.ts",
        status: "GAP",
      },
    ],
  },
  {
    id: "state",
    label: "State Management",
    pdfScore: 8.0,
    institutionalGrade: 9.0,
    items: [
      {
        claim: "6 Zustand stores: account, system, risk, preferences, auth, tableQuery",
        actual: "Repo memiliki 10+ stores: useAccountStore, useSystemStore, useRiskStore, usePreferencesStore, useAuthStore, useTableQueryStore, useAuthorityStore, useSessionStore, useToastStore, usePipelineDagStore, useActionThrottleStore, useWorkspaceStore. Lebih lengkap dari yang didokumentasikan.",
        file: "store/*.ts",
        status: "EXCEEDS",
      },
      {
        claim: "useLivePipeline hook: REST initial load → WS live updates → store sync → mode=DEGRADED on disconnect",
        actual: "Terverifikasi sempurna di hooks/useLivePipeline.ts. fetchLatestPipelineResult() → connectLiveUpdates() → setLatestPipelineResult / updateTrade / setPreferences / setMode('DEGRADED').",
        file: "hooks/useLivePipeline.ts",
        status: "VERIFIED",
      },
      {
        claim: "React Query @tanstack/react-query 5.66.9 untuk REST dengan stale-while-revalidate",
        actual: "Terverifikasi di package.json: @tanstack/react-query ^5.66.9. hooks/queries/ memiliki useTradesQuery, useAuditQuery, usePreferencesQuery.",
        file: "package.json + hooks/queries/*.ts",
        status: "VERIFIED",
      },
      {
        claim: "Message bus layer antara WebSocket dan stores (16ms RAF batching)",
        actual: "TIDAK ADA. wsService.ts langsung memanggil onEvent() per message tanpa batching. Ini adalah GAP terbesar — setiap WS message langsung trigger store update → React re-render.",
        file: "services/wsService.ts",
        status: "GAP",
      },
      {
        claim: "Web Worker untuk computation offloading (candle aggregation, indicators)",
        actual: "Tidak ada Web Worker di repo. Semua komputasi terjadi di main thread.",
        status: "GAP",
      },
      {
        claim: "Zod schema validation pada semua incoming WS data",
        actual: "Terverifikasi. WsEventSchema di schema/wsEventSchema.ts menggunakan z.discriminatedUnion untuk validasi semua event types. wsService.ts baris 37: WsEventSchema.parse(parsed).",
        file: "schema/wsEventSchema.ts + services/wsService.ts",
        status: "VERIFIED",
      },
    ],
  },
  {
    id: "rendering",
    label: "Table Rendering",
    pdfScore: 7.5,
    institutionalGrade: 9.0,
    items: [
      {
        claim: "@tanstack/react-virtual untuk large list virtualization",
        actual: "Terverifikasi. Package.json: @tanstack/react-virtual ^3.11.2. components/primitives/VirtualList.tsx mengimplementasikan virtual rows.",
        file: "components/primitives/VirtualList.tsx",
        status: "VERIFIED",
      },
      {
        claim: "URL-synced pagination (useTableQueryStore)",
        actual: "Terverifikasi. hooks/useUrlSyncedTableQuery.ts + store/useTableQueryStore.ts. Trades page menggunakan keduanya.",
        file: "hooks/useUrlSyncedTableQuery.ts",
        status: "VERIFIED",
      },
      {
        claim: "React.memo per row component untuk prevent re-render",
        actual: "Belum konsisten. TradesTable.tsx tidak menggunakan React.memo pada row components. VirtualList.tsx tidak memiliki row memoization.",
        file: "components/TradesTable.tsx",
        status: "GAP",
      },
      {
        claim: "CSS-only flash animations untuk price changes",
        actual: "components/ui/AnimatedNumber.tsx ada, tapi menggunakan Framer Motion bukan CSS-only. Flash via React state = re-render driven, bukan CSS transition direct.",
        file: "components/ui/AnimatedNumber.tsx",
        status: "PARTIAL",
      },
      {
        claim: "Monospace font untuk semua numerical data",
        actual: "Design token --font-mono='Share Tech Mono, Space Mono' sudah ada. globals.css mendefinisikan .num class. Penggunaan belum konsisten di seluruh table cells.",
        file: "app/globals.css",
        status: "PARTIAL",
      },
      {
        claim: "requestAnimationFrame batching untuk DOM updates",
        actual: "Tidak ada rAF batching. Trades page dan table components update langsung dari store tanpa rAF batching layer.",
        status: "GAP",
      },
    ],
  },
  {
    id: "hierarchy",
    label: "Information Hierarchy",
    pdfScore: 8.5,
    institutionalGrade: 9.5,
    items: [
      {
        claim: "14+ dashboard pages dengan clear routing dan App Router",
        actual: "Terverifikasi. Repo memiliki 16 routes: /, /cockpit, /pipeline, /trades, /trades/signals, /signals, /accounts, /risk, /news, /journal, /probability, /prices, /ea-manager, /prop-firm, /settings, /audit. Plus (admin)/audit.",
        file: "app/(root)/*/page.tsx",
        status: "EXCEEDS",
      },
      {
        claim: "RBAC 5 roles: viewer, operator, risk_admin, config_admin, approver",
        actual: "Terverifikasi. contracts/authority.ts + components/auth/RequireRole.tsx + contracts/complianceSurface.ts. 5 roles dengan granular permissions per page.",
        file: "contracts/authority.ts",
        status: "VERIFIED",
      },
      {
        claim: "Glass-morphism dark palette dengan institutional design",
        actual: "Terverifikasi. globals.css: --bg-base=#050a14 (deep navy), --accent=#f5a623 (wolf gold), --green/#red/#cyan status colors. design token system lengkap.",
        file: "app/globals.css",
        status: "VERIFIED",
      },
      {
        claim: "Persistent status bar selalu visible (P&L, risk, health)",
        actual: "Header.tsx ada tapi minimal. Tidak ada persistent P&L/risk ribbon yang selalu visible di semua pages. DegradationBanner ada tapi hanya muncul saat DEGRADED.",
        file: "components/layout/Header.tsx",
        status: "GAP",
      },
      {
        claim: "Command palette (Ctrl+K) untuk keyboard navigation",
        actual: "Tidak ada. Tidak ada keyboard shortcut system atau command palette di repo.",
        status: "GAP",
      },
      {
        claim: "Customizable multi-panel layout (drag, resize)",
        actual: "components/layout/WorkspaceManager.tsx ada! store/useWorkspaceStore.ts + contracts/workspace.ts menunjukkan workspace management. Perlu verifikasi level implementasinya.",
        file: "components/layout/WorkspaceManager.tsx",
        status: "PARTIAL",
      },
    ],
  },
  {
    id: "security",
    label: "Security & Governance",
    pdfScore: 9.5,
    institutionalGrade: 9.5,
    items: [
      {
        claim: "Dashboard READ-ONLY — zero write authority ke trading system",
        actual: "Terverifikasi via contracts/authority.ts + hooks/useAuthoritySurface.ts + components/actions/ProtectedActionButton.tsx. Semua mutations melalui useProtectedMutation dengan authority check.",
        file: "contracts/authority.ts + hooks/useAuthoritySurface.ts",
        status: "VERIFIED",
      },
      {
        claim: "Constitutional separation: Analysis → Decision → Execution → Advisory",
        actual: "Terverifikasi. contracts/complianceSurface.ts mendefinisikan compliance zones. PageComplianceBanner + ComplianceBanner enforce per-page compliance state.",
        file: "contracts/complianceSurface.ts",
        status: "VERIFIED",
      },
      {
        claim: "Signal deduplication, throttling, dan expiration enforcement",
        actual: "store/useActionThrottleStore.ts + hooks/useActionThrottle.ts + hooks/mutations/useProtectedMutation.ts mengimplementasikan throttle dan dedup.",
        file: "store/useActionThrottleStore.ts",
        status: "VERIFIED",
      },
      {
        claim: "Violation logging dan audit trail",
        actual: "Terverifikasi. services/auditService.ts + hooks/queries/useAuditQuery.ts + app/(admin)/audit/page.tsx. Audit trail lengkap dengan RBAC gate (admin-only route).",
        file: "services/auditService.ts + app/(admin)/audit/",
        status: "VERIFIED",
      },
      {
        claim: "JWT auth dengan RBAC granular",
        actual: "Terverifikasi. lib/auth.ts + store/useAuthStore.ts + components/auth/RequireRole.tsx. Session management via serverAuth.ts + session.ts.",
        file: "lib/auth.ts + lib/serverAuth.ts",
        status: "VERIFIED",
      },
    ],
  },
  {
    id: "pipeline",
    label: "Pipeline Architecture",
    pdfScore: 10,
    institutionalGrade: 9.0,
    items: [
      {
        claim: "15-layer analysis pipeline visualization",
        actual: "components/panels/PipelineDagCanvas.tsx + components/panels/PipelinePanel.tsx. schema/pipelineDagSchema.ts + services/pipelineDagService.ts. store/usePipelineDagStore.ts. Pipeline DAG visualization lengkap.",
        file: "components/panels/PipelineDagCanvas.tsx",
        status: "VERIFIED",
      },
      {
        claim: "8-phase halt-safe DAG orchestration (backend)",
        actual: "Frontend memiliki: schema/pipelineDagSchema.ts + contracts/pipelineDag.ts mendefinisikan DAG structure. pipelineDagService.ts fetch pipeline state. Orchestration ada di backend (Python).",
        file: "schema/pipelineDagSchema.ts",
        status: "VERIFIED",
      },
      {
        claim: "L12 Verdict Engine sebagai SOLE AUTHORITY — 9-gate constitutional check",
        actual: "VerdictCard.tsx + TakeSignalForm.tsx menampilkan L12 verdicts. contracts/authority.ts enforces read-only. Verdict ditampilkan tapi tidak bisa dioverride dari FE.",
        file: "components/VerdictCard.tsx + components/TakeSignalForm.tsx",
        status: "VERIFIED",
      },
      {
        claim: "LiveContextBus singleton state machine (backend)",
        actual: "Frontend side: useLivePipeline.ts menjadi consumer-side state machine. connectLiveUpdates() di wsService.ts adalah FE equivalent. Backend LiveContextBus tidak visible dari FE.",
        file: "hooks/useLivePipeline.ts",
        status: "VERIFIED",
      },
    ],
  },
];

// ── Helper components ─────────────────────────────────────────

const STATUS_META: Record<Status, { label: string; color: string; bg: string; border: string }> = {
  VERIFIED: { label: "VERIFIED", color: "var(--green)", bg: "var(--green-glow)", border: "var(--border-success)" },
  PARTIAL:  { label: "PARTIAL",  color: "var(--yellow)", bg: "var(--yellow-glow)", border: "rgba(255,215,64,0.3)" },
  GAP:      { label: "GAP",      color: "var(--red)", bg: "var(--red-glow)", border: "var(--border-danger)" },
  EXCEEDS:  { label: "EXCEEDS",  color: "var(--cyan)", bg: "var(--cyan-glow)", border: "rgba(0,229,255,0.3)" },
};

function StatusBadge({ status }: { status: Status }) {
  const m = STATUS_META[status];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "2px 8px",
        borderRadius: "var(--radius-sm)",
        background: m.bg,
        border: `1px solid ${m.border}`,
        color: m.color,
        fontFamily: "var(--font-mono)",
        fontSize: 9,
        fontWeight: 700,
        letterSpacing: "0.08em",
        whiteSpace: "nowrap",
      }}
    >
      {m.label}
    </span>
  );
}

function ScoreBar({ value, max = 10, color }: { value: number; max?: number; color: string }) {
  const pct = (value / max) * 100;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div
        style={{
          flex: 1,
          height: 4,
          background: "var(--bg-elevated)",
          borderRadius: 2,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            background: color,
            borderRadius: 2,
            transition: "width 0.4s ease",
          }}
        />
      </div>
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          fontWeight: 700,
          color,
          minWidth: 36,
          textAlign: "right",
        }}
      >
        {value}
      </span>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────

export default function ArchitectureAuditPage() {
  const [activeDim, setActiveDim] = useState<string>("websocket");
  const [expandedItem, setExpandedItem] = useState<number | null>(null);

  const dim = DIMENSIONS.find((d) => d.id === activeDim)!;

  // Summary counts across all dimensions
  const allItems = DIMENSIONS.flatMap((d) => d.items);
  const counts = {
    VERIFIED: allItems.filter((i) => i.status === "VERIFIED").length,
    PARTIAL:  allItems.filter((i) => i.status === "PARTIAL").length,
    GAP:      allItems.filter((i) => i.status === "GAP").length,
    EXCEEDS:  allItems.filter((i) => i.status === "EXCEEDS").length,
  };

  const dimCounts = (d: Dimension) => ({
    VERIFIED: d.items.filter((i) => i.status === "VERIFIED").length,
    PARTIAL:  d.items.filter((i) => i.status === "PARTIAL").length,
    GAP:      d.items.filter((i) => i.status === "GAP").length,
    EXCEEDS:  d.items.filter((i) => i.status === "EXCEEDS").length,
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

      {/* ── Page header ── */}
      <div>
        <h1
          style={{
            fontSize: 22,
            fontWeight: 800,
            letterSpacing: "0.06em",
            color: "var(--text-primary)",
            margin: 0,
            fontFamily: "var(--font-display)",
          }}
        >
          ARCHITECTURE AUDIT
        </h1>
        <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3 }}>
          Script PDF analysis vs kondisi aktual repo — TUYUL-FX WOLF 15-LAYER SYSTEM
        </p>
      </div>

      {/* ── Script metadata banner ── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: 10,
        }}
      >
        {[
          { label: "Script Type", value: "Python ReportLab PDF Generator" },
          { label: "Document", value: "Institutional-Grade Architecture Analysis v1.0" },
          { label: "Analysis Date", value: "March 15, 2026" },
          { label: "Prepared For", value: "kadektjx@gmail.com" },
          { label: "System Version", value: "v7.4r∞ (Locked, Live-Ready)" },
          { label: "Overall Score (PDF)", value: "8.75 / 10" },
        ].map(({ label, value }) => (
          <div
            key={label}
            className="card"
            style={{ padding: "10px 14px" }}
          >
            <div style={{ fontSize: 9, fontWeight: 700, color: "var(--text-muted)", letterSpacing: "0.08em", marginBottom: 4, fontFamily: "var(--font-mono)" }}>
              {label.toUpperCase()}
            </div>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-primary)" }}>
              {value}
            </div>
          </div>
        ))}
      </div>

      {/* ── Summary counts ── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
        {(["VERIFIED", "EXCEEDS", "PARTIAL", "GAP"] as Status[]).map((s) => {
          const m = STATUS_META[s];
          return (
            <div
              key={s}
              className="card"
              style={{
                padding: "14px 16px",
                borderColor: m.border,
                background: m.bg,
                display: "flex",
                flexDirection: "column",
                gap: 4,
              }}
            >
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: m.color, fontWeight: 700, letterSpacing: "0.08em" }}>
                {s}
              </div>
              <div style={{ fontSize: 28, fontWeight: 900, color: m.color, fontFamily: "var(--font-display)", lineHeight: 1 }}>
                {counts[s]}
              </div>
              <div style={{ fontSize: 10, color: "var(--text-muted)" }}>claims checked</div>
            </div>
          );
        })}
      </div>

      {/* ── Main layout: sidebar + detail ── */}
      <div style={{ display: "grid", gridTemplateColumns: "240px 1fr", gap: 14 }}>

        {/* ── Left: dimension list ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {DIMENSIONS.map((d) => {
            const c = dimCounts(d);
            const isActive = activeDim === d.id;
            const scoreColor = d.pdfScore >= 9.5 ? "var(--green)" : d.pdfScore >= 8.5 ? "var(--cyan)" : d.pdfScore >= 8.0 ? "var(--yellow)" : "var(--red)";
            return (
              <button
                key={d.id}
                onClick={() => { setActiveDim(d.id); setExpandedItem(null); }}
                aria-selected={isActive}
                style={{
                  padding: "10px 12px",
                  borderRadius: "var(--radius-md)",
                  border: `1px solid ${isActive ? "var(--accent)" : "var(--border-default)"}`,
                  background: isActive ? "var(--accent-muted)" : "var(--bg-card)",
                  cursor: "pointer",
                  textAlign: "left",
                  display: "flex",
                  flexDirection: "column",
                  gap: 6,
                }}
              >
                <div style={{ fontSize: 11, fontWeight: isActive ? 700 : 500, color: isActive ? "var(--accent)" : "var(--text-secondary)" }}>
                  {d.label}
                </div>
                <ScoreBar value={d.pdfScore} color={scoreColor} />
                <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                  {c.VERIFIED > 0 && (
                    <span style={{ fontSize: 8, color: "var(--green)", fontFamily: "var(--font-mono)" }}>
                      {c.VERIFIED}V
                    </span>
                  )}
                  {c.EXCEEDS > 0 && (
                    <span style={{ fontSize: 8, color: "var(--cyan)", fontFamily: "var(--font-mono)" }}>
                      {c.EXCEEDS}E
                    </span>
                  )}
                  {c.PARTIAL > 0 && (
                    <span style={{ fontSize: 8, color: "var(--yellow)", fontFamily: "var(--font-mono)" }}>
                      {c.PARTIAL}P
                    </span>
                  )}
                  {c.GAP > 0 && (
                    <span style={{ fontSize: 8, color: "var(--red)", fontFamily: "var(--font-mono)" }}>
                      {c.GAP}G
                    </span>
                  )}
                </div>
              </button>
            );
          })}

          {/* ── Score comparison ── */}
          <div
            className="card"
            style={{ padding: "12px 14px", marginTop: 8, display: "flex", flexDirection: "column", gap: 8 }}
          >
            <div style={{ fontSize: 9, fontWeight: 700, color: "var(--text-muted)", letterSpacing: "0.08em", fontFamily: "var(--font-mono)" }}>
              OVERALL SCORES
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <div>
                <div style={{ fontSize: 9, color: "var(--text-muted)", marginBottom: 3 }}>PDF Claim</div>
                <ScoreBar value={8.75} color="var(--accent)" />
              </div>
              <div>
                <div style={{ fontSize: 9, color: "var(--text-muted)", marginBottom: 3 }}>Institutional Grade</div>
                <ScoreBar value={9.25} color="var(--cyan)" />
              </div>
            </div>
          </div>
        </div>

        {/* ── Right: dimension detail ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>

          {/* Dimension header */}
          <div
            className="card"
            style={{ padding: "14px 18px", display: "flex", alignItems: "center", gap: 16 }}
          >
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 16, fontWeight: 800, color: "var(--text-primary)", fontFamily: "var(--font-display)", letterSpacing: "0.04em" }}>
                {dim.label.toUpperCase()}
              </div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                {dim.items.length} claims verified against actual repo files
              </div>
            </div>
            <div style={{ display: "flex", gap: 16 }}>
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: 9, color: "var(--text-muted)", fontFamily: "var(--font-mono)", letterSpacing: "0.06em" }}>PDF SCORE</div>
                <div style={{ fontSize: 22, fontWeight: 900, color: "var(--accent)", fontFamily: "var(--font-display)" }}>
                  {dim.pdfScore}
                </div>
              </div>
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: 9, color: "var(--text-muted)", fontFamily: "var(--font-mono)", letterSpacing: "0.06em" }}>INST. GRADE</div>
                <div style={{ fontSize: 22, fontWeight: 900, color: "var(--cyan)", fontFamily: "var(--font-display)" }}>
                  {dim.institutionalGrade}
                </div>
              </div>
            </div>
          </div>

          {/* Claim items */}
          {dim.items.map((item, idx) => {
            const m = STATUS_META[item.status];
            const isOpen = expandedItem === idx;
            return (
              <div
                key={idx}
                className="card"
                style={{
                  padding: 0,
                  overflow: "hidden",
                  borderColor: isOpen ? m.border : "var(--border-default)",
                  transition: "border-color 0.15s",
                }}
              >
                {/* Header row */}
                <button
                  onClick={() => setExpandedItem(isOpen ? null : idx)}
                  style={{
                    width: "100%",
                    padding: "12px 16px",
                    background: isOpen ? m.bg : "transparent",
                    border: "none",
                    cursor: "pointer",
                    textAlign: "left",
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 12,
                    transition: "background 0.15s",
                  }}
                >
                  <StatusBadge status={item.status} />
                  <div style={{ flex: 1, fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.5 }}>
                    {item.claim}
                  </div>
                  <span
                    style={{
                      fontSize: 10,
                      color: "var(--text-faint)",
                      flexShrink: 0,
                      fontFamily: "var(--font-mono)",
                      marginTop: 1,
                    }}
                  >
                    {isOpen ? "▲" : "▼"}
                  </span>
                </button>

                {/* Expanded detail */}
                {isOpen && (
                  <div
                    style={{
                      padding: "0 16px 14px",
                      display: "flex",
                      flexDirection: "column",
                      gap: 8,
                      borderTop: `1px solid ${m.border}`,
                    }}
                  >
                    <div style={{ paddingTop: 10 }}>
                      <div
                        style={{
                          fontSize: 9,
                          fontWeight: 700,
                          color: "var(--text-muted)",
                          letterSpacing: "0.08em",
                          fontFamily: "var(--font-mono)",
                          marginBottom: 6,
                        }}
                      >
                        ACTUAL REPO STATE
                      </div>
                      <p
                        style={{
                          fontSize: 12,
                          color: "var(--text-primary)",
                          lineHeight: 1.6,
                          margin: 0,
                        }}
                      >
                        {item.actual}
                      </p>
                    </div>
                    {item.file && (
                      <div
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 6,
                          padding: "4px 10px",
                          background: "var(--bg-elevated)",
                          borderRadius: "var(--radius-sm)",
                          border: "1px solid var(--border-default)",
                          alignSelf: "flex-start",
                        }}
                      >
                        <span style={{ fontSize: 9, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>FILE</span>
                        <span style={{ fontSize: 10, color: "var(--accent)", fontFamily: "var(--font-mono)", fontWeight: 600 }}>
                          {item.file}
                        </span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* ── GAP action items ── */}
      <div className="card" style={{ padding: "16px 18px" }}>
        <div
          style={{
            fontSize: 13,
            fontWeight: 800,
            color: "var(--red)",
            fontFamily: "var(--font-display)",
            letterSpacing: "0.04em",
            marginBottom: 12,
            borderBottom: "1px solid var(--border-danger)",
            paddingBottom: 8,
          }}
        >
          IDENTIFIED GAPS — PRIORITY ACTION LIST
        </div>
        <div style={{ display: "grid", gap: 8 }}>
          {[
            { pri: "P1", effort: "4h", title: "Message batching (16ms RAF window)", detail: "wsService.ts onEvent() perlu di-wrap dengan requestAnimationFrame buffer sebelum store dispatch.", dim: "State Mgmt" },
            { pri: "P1", effort: "2h", title: "React.memo pada TradesTable row components", detail: "Wrap row renderer di TradesTable.tsx dan VirtualList.tsx dengan React.memo + stable key.", dim: "Table Render" },
            { pri: "P1", effort: "3h", title: "Persistent status bar", detail: "Tambahkan komponen sticky di Header.tsx: live equity, risk level, WS status, P&L session.", dim: "Info Hierarchy" },
            { pri: "P2", effort: "3d", title: "Exponential backoff reconnect di websocket.ts", detail: "Ganti RECONNECT_DELAY_MS fixed dengan exponential: 1s→2s→4s→8s→16s→30s cap + jitter.", dim: "WebSocket" },
            { pri: "P2", effort: "2d", title: "SSE fallback layer di wsService.ts", detail: "Setelah 30s WS down, switch ke SSE atau REST polling sebelum full DEGRADED mode.", dim: "WebSocket" },
            { pri: "P2", effort: "3d", title: "Web Worker untuk indicator computation", detail: "Pindahkan candle aggregation dan indicator calc ke Worker thread, post results ke main thread.", dim: "State Mgmt" },
            { pri: "P3", effort: "1w", title: "Command palette (Ctrl+K)", detail: "Keyboard-first navigation untuk semua routes, actions, dan settings.", dim: "Info Hierarchy" },
            { pri: "P3", effort: "1w", title: "Per-message WebSocket compression", detail: "Tambahkan deflate compression di server-side WS upgrade dan FE connect options.", dim: "WebSocket" },
          ].map(({ pri, effort, title, detail, dim }, i) => (
            <div
              key={i}
              style={{
                display: "grid",
                gridTemplateColumns: "48px 36px 1fr auto",
                gap: 12,
                alignItems: "start",
                padding: "10px 0",
                borderBottom: i < 7 ? "1px solid var(--border-subtle)" : "none",
              }}
            >
              <span
                style={{
                  padding: "2px 6px",
                  borderRadius: "var(--radius-sm)",
                  background: pri === "P1" ? "var(--red-glow)" : pri === "P2" ? "var(--yellow-glow)" : "var(--bg-elevated)",
                  border: `1px solid ${pri === "P1" ? "var(--border-danger)" : pri === "P2" ? "rgba(255,215,64,0.3)" : "var(--border-default)"}`,
                  color: pri === "P1" ? "var(--red)" : pri === "P2" ? "var(--yellow)" : "var(--text-muted)",
                  fontFamily: "var(--font-mono)",
                  fontSize: 9,
                  fontWeight: 700,
                  textAlign: "center",
                }}
              >
                {pri}
              </span>
              <span style={{ fontSize: 9, color: "var(--text-faint)", fontFamily: "var(--font-mono)", paddingTop: 3 }}>
                {effort}
              </span>
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-primary)", marginBottom: 3 }}>
                  {title}
                </div>
                <div style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.5 }}>
                  {detail}
                </div>
              </div>
              <span
                style={{
                  padding: "2px 8px",
                  borderRadius: "var(--radius-sm)",
                  background: "var(--bg-elevated)",
                  border: "1px solid var(--border-default)",
                  fontSize: 9,
                  color: "var(--text-muted)",
                  fontFamily: "var(--font-mono)",
                  whiteSpace: "nowrap",
                }}
              >
                {dim}
              </span>
            </div>
          ))}
        </div>
      </div>

    </div>
  );
}
