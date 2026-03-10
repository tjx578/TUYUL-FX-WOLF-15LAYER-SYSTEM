"use client";

import { useSystemStore } from "@/store/useSystemStore";

export default function DegradationBanner() {
  const mode = useSystemStore((s) => s.mode);
  const wsStatus = useSystemStore((s) => s.wsStatus);
  const system = useSystemStore((s) => s.system);

  const shouldShow = mode === "DEGRADED" || wsStatus === "RECONNECTING";
  if (!shouldShow) {
    return null;
  }

  const reason =
    system?.reason ||
    (wsStatus !== "CONNECTED"
      ? "Live update channel is unstable; UI is operating in defensive mode."
      : "System reported degraded mode.");

  return (
    <section
      className="mb-4 rounded-xl border border-amber-400/40 bg-amber-500/20 px-4 py-3 text-sm text-amber-100"
      role="status"
      aria-live="polite"
    >
      <p className="font-semibold">Degraded Mode Active</p>
      <p className="opacity-90">{reason}</p>
    </section>
  );
}