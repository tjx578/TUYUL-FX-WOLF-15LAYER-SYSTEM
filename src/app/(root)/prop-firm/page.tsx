"use client";

import { useState } from "react";
import { useAccounts } from "@/features/accounts/api/accounts.api";
import { usePropFirmPhase, usePropFirmStatus } from "@/shared/api/propfirm.api";

interface PropFirmStatus {
  allowed: boolean;
  code: string;
  details?: string;
}

interface PropFirmPhase {
  phase_name: string;
  progress_percent: number;
}

export default function PropFirmPage() {
  const { data: accounts } = useAccounts();
  const [selectedAccountId, setSelectedAccountId] = useState("");
  const activeAccountId = selectedAccountId || accounts?.[0]?.account_id || "";

  const { data: status } = usePropFirmStatus(activeAccountId) as { data: PropFirmStatus | undefined };
  const { data: phase } = usePropFirmPhase(activeAccountId) as { data: PropFirmPhase | undefined };

  return (
    <div className="space-y-4">
      {/* Account selector */}
      {accounts && accounts.length > 1 && (
        <div className="rounded-xl border p-4">
          <label className="font-semibold" htmlFor="account-select">Account</label>
          <select
            id="account-select"
            className="ml-3 rounded border px-2 py-1 text-sm"
            value={activeAccountId}
            onChange={(e) => setSelectedAccountId(e.target.value)}
          >
            {accounts.map((a) => (
              <option key={a.account_id} value={a.account_id}>
                {a.account_name ?? a.account_id}
              </option>
            ))}
          </select>
        </div>
      )}

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