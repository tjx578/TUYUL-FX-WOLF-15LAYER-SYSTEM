"use client";

import { Card } from "@/components/primitives/Card";

export default function EntryGovernancePanel() {
  return (
    <Card>
      <h3 className="text-sm font-semibold text-slate-200">Entry Governance</h3>
      <p className="mt-2 text-xs text-slate-400">
        Governance gates are backend-authoritative and reflected here as observability only.
      </p>
    </Card>
  );
}
