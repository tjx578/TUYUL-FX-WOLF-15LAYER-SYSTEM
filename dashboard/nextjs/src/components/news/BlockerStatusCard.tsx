"use client";

import { useCalendarBlocker } from "@/lib/api";

interface BlockerStatusCardProps {
  symbol?: string;
}

export default function BlockerStatusCard({ symbol }: BlockerStatusCardProps) {
  const { data, isLoading, isError } = useCalendarBlocker(symbol);

  const isLocked = Boolean(data?.is_locked);

  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-950 p-4">
      <div className="mb-3 text-sm font-semibold text-neutral-200">Blocker Status</div>

      {isLoading ? <div className="text-sm text-neutral-400">Evaluating blocker...</div> : null}
      {isError ? <div className="text-sm text-red-300">Failed to fetch blocker status.</div> : null}

      {!isLoading && !isError ? (
        <>
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm text-neutral-300">Trading Window</span>
            <span
              className={`rounded px-2 py-0.5 text-xs font-semibold ${isLocked ? "bg-red-900/70 text-red-100" : "bg-lime-800/70 text-lime-100"}`}
            >
              {isLocked ? "LOCKED" : "OPEN"}
            </span>
          </div>

          <div className="mt-2 text-xs text-neutral-400">
            checked at: {data?.checked_at ?? "-"}
          </div>

          <div className="mt-2 text-sm text-neutral-200">
            {isLocked ? data?.lock_reason ?? "High-impact news lock active." : "No active lock."}
          </div>

          <div className="mt-2 text-xs text-neutral-400">
            upcoming events in window: {data?.upcoming_count ?? 0}
          </div>
        </>
      ) : null}
    </div>
  );
}
