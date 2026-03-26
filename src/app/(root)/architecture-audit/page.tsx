// ============================================================
// TUYUL FX Wolf-15 – Architecture Documentation Page (Server Component)
// Source of truth: docs/architecture/audit-manifest.json
// This page renders the canonical architecture doc index.
// The interactive explorer is a client component.
// ============================================================

import { AUDIT_MANIFEST, docCountsByDomain } from "./_audit-data";
import { DocExplorer } from "./_audit-explorer";

// ── Page (Server Component) ──────────────────────────────────

export default function ArchitectureAuditPage() {
  const counts = docCountsByDomain();
  const totalDocs = AUDIT_MANIFEST.docs.length;

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
          ARCHITECTURE DOCUMENTATION
        </h1>
        <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3 }}>
          Canonical architecture reference — source:{" "}
          <span style={{ fontFamily: "var(--font-mono)", color: "var(--accent)" }}>
            {AUDIT_MANIFEST.source}
          </span>
          {" "}· {totalDocs} documents · updated {AUDIT_MANIFEST.generated_at}
        </p>
      </div>

      {/* ── Domain summary cards ── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
          gap: 10,
        }}
      >
        {AUDIT_MANIFEST.domains.map((domain) => (
          <div
            key={domain.id}
            className="card"
            style={{ padding: "12px 14px" }}
          >
            <div
              style={{
                fontSize: 9,
                fontWeight: 700,
                color: "var(--text-muted)",
                letterSpacing: "0.08em",
                marginBottom: 4,
                fontFamily: "var(--font-mono)",
              }}
            >
              {domain.label.toUpperCase()}
            </div>
            <div
              style={{
                fontSize: 24,
                fontWeight: 900,
                color: "var(--cyan)",
                fontFamily: "var(--font-display)",
                lineHeight: 1,
              }}
            >
              {counts[domain.id] ?? 0}
            </div>
            <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>
              {counts[domain.id] === 1 ? "document" : "documents"}
            </div>
          </div>
        ))}
      </div>

      {/* ── Interactive doc explorer (client component) ── */}
      <DocExplorer />

    </div>
  );
}
