"use client";

import { useEffect, useRef } from "react";
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

  // Use wall-clock elapsed time to avoid setTimeout drift (especially in
  // background tabs where timers are throttled).
  const deadlineRef = useRef<number | null>(null);
  useEffect(() => {
    if (expiringInSeconds === null || expiringInSeconds <= 0) {
      deadlineRef.current = null;
      return;
    }
    // Capture absolute deadline on first non-null value
    if (deadlineRef.current === null) {
      deadlineRef.current = Date.now() + expiringInSeconds * 1000;
    }
    const timer = setInterval(() => {
      const remaining = Math.max(0, Math.round(((deadlineRef.current ?? 0) - Date.now()) / 1000));
      setExpiringInSeconds(remaining);
    }, 1000);
    return () => clearInterval(timer);
  }, [expiringInSeconds === null || expiringInSeconds <= 0]); // only re-run on start/stop transitions

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
