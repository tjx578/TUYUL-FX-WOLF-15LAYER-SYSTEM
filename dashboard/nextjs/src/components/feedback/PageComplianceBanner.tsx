"use client";

import { useMemo } from "react";
import type { CompliancePage } from "@/contracts/complianceSurface";
import { buildComplianceSurface } from "@/lib/complianceSurface";
import { useRiskStore } from "@/store/useRiskStore";

interface PageComplianceBannerProps {
  page: CompliancePage;
}

function toneClass(tone: "info" | "warning" | "error"): string {
  if (tone === "error") {
    return "bg-rose-500/20 border-rose-400/40 text-rose-100";
  }
  if (tone === "warning") {
    return "bg-amber-500/20 border-amber-400/40 text-amber-100";
  }
  return "bg-sky-500/20 border-sky-400/40 text-sky-100";
}

export default function PageComplianceBanner({ page }: PageComplianceBannerProps) {
  const complianceState = useRiskStore((state) => state.complianceState);

  const surface = useMemo(
    () => buildComplianceSurface(page, complianceState),
    [page, complianceState],
  );

  if (!surface) {
    return null;
  }

  return (
    <section
      className={`mb-4 rounded-xl border px-4 py-3 text-sm ${toneClass(surface.tone)}`}
      role="status"
      aria-live="polite"
    >
      <p className="font-semibold">{surface.title}</p>
      <p className="opacity-90">{surface.description}</p>
      <p className="mt-1 text-xs opacity-80">State: {surface.state}</p>
    </section>
  );
}