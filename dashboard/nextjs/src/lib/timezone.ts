// ============================================================
// TUYUL FX Wolf-15 — Timezone Utilities
// ============================================================

const TZ = process.env.NEXT_PUBLIC_TIMEZONE || "Asia/Singapore";

export function nowInTz(): Date {
  return new Date(new Date().toLocaleString("en-US", { timeZone: TZ }));
}

export function formatTime(ts: number | string | Date, tz = TZ): string {
  const d = typeof ts === "object" ? ts : new Date(ts);
  return d.toLocaleTimeString("en-US", {
    timeZone: tz,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function formatDate(ts: number | string | Date, tz = TZ): string {
  const d = typeof ts === "object" ? ts : new Date(ts);
  return d.toLocaleDateString("en-US", {
    timeZone: tz,
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export function formatDateTime(ts: number | string | Date, tz = TZ): string {
  return `${formatDate(ts, tz)} ${formatTime(ts, tz)}`;
}

export function sessionLabel(): string {
  const h = nowInTz().getHours();
  if (h >= 0 && h < 8) return "ASIA";
  if (h >= 8 && h < 13) return "LONDON";
  if (h >= 13 && h < 17) return "NY";
  if (h >= 17 && h < 21) return "NY_LATE";
  return "OFF_HOURS";
}

export function msUntilNextHour(): number {
  const now = new Date();
  return (60 - now.getMinutes()) * 60000 - now.getSeconds() * 1000;
}
