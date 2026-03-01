"use client";

import { restartEA, useEALogs, useEAStatus } from "@/lib/api";
import type { EALog } from "@/types";

export default function EAManagerPage() {
  const { data: status } = useEAStatus();
  const { data: logs, mutate } = useEALogs();

  return (
    <div className="space-y-4">
      <div className="rounded-xl border p-4">
        <div className="font-semibold">EA Bridge Status</div>
        <div className="text-sm">Healthy: {String(status?.healthy ?? false)}</div>
        <button
          className="mt-3 rounded-lg border px-3 py-1"
          onClick={async () => {
            await restartEA();
            await mutate();
          }}
        >
          RESTART EA ENGINE
        </button>
      </div>

      <div className="rounded-xl border p-4">
        <div className="font-semibold mb-2">EA Logs</div>
        <ul className="space-y-1 text-sm">
          {logs?.map((l: EALog) => (
            <li key={l.id}>{l.timestamp} — {l.message}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
