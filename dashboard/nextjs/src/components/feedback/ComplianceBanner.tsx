"use client";

import { useRiskStore } from "@/store/useRiskStore";

function bannerTone(state?: string): string | null {
  if (!state || state === "COMPLIANCE_NORMAL") return null;
  if (state.includes("CAUTION")) return "bg-amber-500/20 border-amber-400/40 text-amber-200";
  if (state.includes("BLOCK")) return "bg-rose-500/20 border-rose-400/40 text-rose-200";
  return "bg-sky-500/20 border-sky-400/40 text-sky-100";
}

export default function ComplianceBanner() {
  const complianceState = useRiskStore((state) => state.complianceState);
  const tone = bannerTone(complianceState);

  if (!tone) return null;

  return (
    <div className={`mb-4 rounded-xl border px-4 py-2 text-sm ${tone}`} role="status" aria-live="polite">
      Compliance state: <strong>{complianceState}</strong>
    </div>
  );
}
