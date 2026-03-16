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
  // Must match backend utils/timezone_utils.py is_trading_session()
  if (h >= 7 && h < 15) return "ASIA";
  if (h >= 15 && h < 21) return "LONDON";
  if (h >= 21 || h < 5) return "NEW_YORK";
  return "OFF_SESSION";
}

export function msUntilNextHour(): number {
  const now = new Date();
  return (60 - now.getMinutes()) * 60000 - now.getSeconds() * 1000;
}
