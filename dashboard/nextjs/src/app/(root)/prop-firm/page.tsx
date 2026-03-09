"use client";

import { usePropFirmPhase, usePropFirmStatus } from "@/lib/api";

interface PropFirmStatus {
  allowed: boolean;
  code: string;
  details?: string;
}

interface PropFirmPhase {
  phase_name: string;
  progress_percent: number;
}

const ACCOUNT_ID = "PRIMARY";

export default function PropFirmPage() {
  const { data: status } = usePropFirmStatus(ACCOUNT_ID) as { data: PropFirmStatus | undefined };
  const { data: phase } = usePropFirmPhase(ACCOUNT_ID) as { data: PropFirmPhase | undefined };

  return (
    <div className="space-y-4">
      <div className="rounded-xl border p-4">
        <div className="font-semibold">Compliance</div>
        <div>Allowed: {String(status?.allowed ?? false)}</div>
        <div>Code: {status?.code ?? "-"}</div>
        <div className="text-sm opacity-80">{status?.details ?? "-"}</div>
      </div>
      <div className="rounded-xl border p-4">
        <div className="font-semibold">Phase</div>
        <div>{phase?.phase_name ?? "-"}</div>
        <div>Progress: {phase?.progress_percent ?? 0}%</div>
      </div>
    </div>
  );
}