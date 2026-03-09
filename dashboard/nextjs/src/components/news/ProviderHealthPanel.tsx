"use client";

import { useCalendarSourceHealth } from "@/lib/api";

export default function ProviderHealthPanel() {
  const { data, isLoading, isError } = useCalendarSourceHealth();

  const rows = Object.entries(data?.sources ?? {});

  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-950 p-4">
      <div className="mb-3 text-sm font-semibold text-neutral-200">Provider Health</div>

      {isLoading ? <div className="text-sm text-neutral-400">Loading health...</div> : null}
      {isError ? <div className="text-sm text-red-300">Failed to load provider health.</div> : null}

      {!isLoading && !isError && rows.length === 0 ? (
        <div className="text-sm text-neutral-400">No provider health records yet.</div>
      ) : null}

      {rows.length > 0 ? (
        <div className="space-y-2">
          {rows.map(([name, item]) => (
            <div key={name} className="rounded border border-neutral-800 bg-neutral-900/70 p-2 text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-neutral-100">{name}</span>
                <span
                  className={`rounded px-2 py-0.5 text-xs ${item.healthy ? "bg-lime-800/70 text-lime-100" : "bg-red-900/70 text-red-100"}`}
                >
                  {item.healthy ? "HEALTHY" : "DEGRADED"}
                </span>
              </div>
              <div className="mt-1 text-xs text-neutral-400">
                last checked: {item.last_checked ?? "-"}
              </div>
              {item.last_error ? (
                <div className="mt-1 text-xs text-red-200">last error: {item.last_error}</div>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
