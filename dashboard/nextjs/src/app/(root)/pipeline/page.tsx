"use client";

// ============================================================
// TUYUL FX Wolf-15 — Pipeline Page (/pipeline)
// Production: DAG canvas, runtime stats, entry governance
// ============================================================

import PipelinePanel from "@/components/panels/PipelinePanel";
import PipelineDagCanvas from "@/components/panels/PipelineDagCanvas";
import EntryGovernancePanel from "@/components/panels/EntryGovernancePanel";
import PageComplianceBanner from "@/components/feedback/PageComplianceBanner";

function SectionWrapper({
  title,
  sub,
  children,
}: {
  title: string;
  sub?: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div>
        <div
          style={{
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: "0.10em",
            color: "var(--text-muted)",
            fontFamily: "var(--font-mono)",
          }}
        >
          {title}
        </div>
        {sub && (
          <div style={{ fontSize: 10, color: "var(--text-faint)", marginTop: 2 }}>
            {sub}
          </div>
        )}
      </div>
      <div className="panel" style={{ padding: 0, overflow: "hidden" }}>
        {children}
      </div>
    </div>
  );
}

export default function PipelinePage() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <PageComplianceBanner page="pipeline" />

      {/* ── Header ── */}
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
          PIPELINE
        </h1>
        <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3 }}>
          L1-L12 multi-layer signal pipeline — DAG topology, gate scoring, entry governance
        </p>
      </div>

      {/* ── Pipeline runtime ── */}
      <SectionWrapper title="RUNTIME" sub="Live layer-by-layer execution state">
        <div style={{ padding: 16 }}>
          <PipelinePanel />
        </div>
      </SectionWrapper>

      {/* ── DAG canvas ── */}
      <SectionWrapper title="DAG TOPOLOGY" sub="Directed acyclic graph — signal flow visualization">
        <PipelineDagCanvas />
      </SectionWrapper>

      {/* ── Entry governance ── */}
      <SectionWrapper title="ENTRY GOVERNANCE" sub="Constitution gates, checklist, approval state">
        <div style={{ padding: 16 }}>
          <EntryGovernancePanel />
        </div>
      </SectionWrapper>
    </div>
  );
}
