const TZ = process.env.NEXT_PUBLIC_TIMEZONE || "Asia/Singapore";

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

export function nowHourInTz(): number {
  const fmt = new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric", hour12: false });
  const parts = fmt.formatToParts(new Date());
  const h = parts.find((p) => p.type === "hour");
  return h ? parseInt(h.value, 10) : 0;
}

export function sessionLabel(): string {
  const h = nowHourInTz();
  if (h >= 7 && h < 15) return "ASIA";
  if (h >= 15 && h < 21) return "LONDON";
  if (h >= 21 || h < 5) return "NEW_YORK";
  return "OFF_SESSION";
}
