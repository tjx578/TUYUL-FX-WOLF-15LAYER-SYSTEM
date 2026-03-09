"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSessionStore } from "@/store/useSessionStore";
import { useSessionRefresh } from "@/hooks/useSessionRefresh";

export default function SessionExpiryModal() {
  const router = useRouter();
  const expiringInSeconds = useSessionStore((state) => state.expiringInSeconds);
  const expiredReason = useSessionStore((state) => state.expiredReason);
  const refreshInFlight = useSessionStore((state) => state.refreshInFlight);
  const setExpiringInSeconds = useSessionStore((state) => state.setExpiringInSeconds);
  const refresh = useSessionRefresh();

  useEffect(() => {
    // Passive countdown simulation hook; backend source can overwrite store values.
    if (expiringInSeconds === null || expiringInSeconds <= 0) {
      return;
    }
    const timer = setTimeout(() => setExpiringInSeconds(expiringInSeconds - 1), 1000);
    return () => clearTimeout(timer);
  }, [expiringInSeconds, setExpiringInSeconds]);

  const shouldShow = Boolean(expiredReason) || (expiringInSeconds !== null && expiringInSeconds <= 60);
  if (!shouldShow) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/70" role="dialog" aria-modal="true" aria-label="Session expiry warning">
      <div className="w-full max-w-md rounded-2xl border border-white/10 bg-slate-900 p-6 text-white shadow-2xl">
        <h2 className="text-lg font-semibold">Session Expiry</h2>
        <p className="mt-2 text-sm text-slate-300">
          {expiredReason
            ? "Your session has expired or refresh failed."
            : `Your session will expire in about ${expiringInSeconds ?? 0} seconds.`}
        </p>
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={refreshInFlight}
            className="rounded-lg border border-cyan-400/40 px-4 py-2 text-sm"
          >
            {refreshInFlight ? "Refreshing..." : "Refresh Session"}
          </button>
          <button
            type="button"
            onClick={() => router.replace("/")}
            className="rounded-lg border border-white/20 px-4 py-2 text-sm"
          >
            Back to Home
          </button>
        </div>
      </div>
    </div>
  );
}
