import type { CompliancePage, ComplianceSurface } from "@/contracts/complianceSurface";

const PAGE_CONTEXT: Record<CompliancePage, string> = {
  dashboard: "Execution controls remain visible but elevated actions may be restricted.",
  trades: "Trade actions can be delayed or blocked under active compliance controls.",
  analysis: "Analysis data remains visible while compliance controls limit execution authority.",
  risk: "Risk views should be prioritized while compliance controls are active.",
  news: "News context is informational only and cannot override compliance gating.",
  journal: "Journaling remains available for full auditability during compliance constraints.",
  accounts: "Account management actions may be restricted while compliance controls are active.",
  pipeline: "Pipeline execution and signal routing may be gated by active compliance controls.",
  settings: "Configuration updates can be gated while compliance controls are active.",
};

export function buildComplianceSurface(
  page: CompliancePage,
  complianceState?: string,
): ComplianceSurface | null {
  if (!complianceState || complianceState === "COMPLIANCE_NORMAL") {
    return null;
  }

  if (complianceState.includes("BLOCK")) {
    return {
      page,
      state: complianceState,
      tone: "error",
      title: "Compliance Block Active",
      description: `${PAGE_CONTEXT[page]} Block-level safeguards are in force until state recovers.`,
    };
  }

  if (complianceState.includes("CAUTION")) {
    return {
      page,
      state: complianceState,
      tone: "warning",
      title: "Compliance Caution",
      description: `${PAGE_CONTEXT[page]} Proceed defensively and verify constraints before action.`,
    };
  }

  return {
    page,
    state: complianceState,
    tone: "info",
    title: "Compliance Notice",
    description: PAGE_CONTEXT[page],
  };
}
