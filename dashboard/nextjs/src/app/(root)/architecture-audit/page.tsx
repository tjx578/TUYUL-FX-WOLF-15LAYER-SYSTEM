// ============================================================
// TUYUL FX Wolf-15 â€” Architecture Audit Page (Server Component)
// Static data rendered server-side for better LCP.
// Interactive explorer is a client component.
// ============================================================

import type { Status } from "./_audit-data";
import { STATUS_META, DIMENSIONS, GAP_ITEMS } from "./_audit-data";
import { AuditExplorer } from "./_audit-explorer";

// â”€â”€ Page (Server Component) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export default function ArchitectureAuditPage() {
  const allItems = DIMENSIONS.flatMap((d) => d.items);
  const counts = {
    VERIFIED: allItems.filter((i) => i.status === "VERIFIED").length,
    PARTIAL: allItems.filter((i) => i.status === "PARTIAL").length,
    GAP: allItems.filter((i) => i.status === "GAP").length,
    EXCEEDS: allItems.filter((i) => i.status === "EXCEEDS").length,
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

      {/* â”€â”€ Page header â”€â”€ */}
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
          Script PDF analysis vs kondisi aktual repo â€” TUYUL-FX WOLF 15-LAYER SYSTEM
        </p>
      </div>

      {/* â”€â”€ Script metadata banner â”€â”€ */}
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
          { label: "System Version", value: "v7.4râˆž (Locked, Live-Ready)" },
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

      {/* â”€â”€ Summary counts â”€â”€ */}
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

      {/* â”€â”€ Interactive dimension explorer (client component) â”€â”€ */}
      <AuditExplorer />

      {/* â”€â”€ GAP action items â”€â”€ */}
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
          IDENTIFIED GAPS â€” PRIORITY ACTION LIST
        </div>
        <div style={{ display: "grid", gap: 8 }}>
          {GAP_ITEMS.map(({ pri, effort, title, detail, dim }, i) => (
            <div
              key={i}
              style={{
                display: "grid",
                gridTemplateColumns: "48px 36px 1fr auto",
                gap: 12,
                alignItems: "start",
                padding: "10px 0",
                borderBottom: i < GAP_ITEMS.length - 1 ? "1px solid var(--border-subtle)" : "none",
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
