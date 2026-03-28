// ============================================================
// TUYUL FX Wolf-15 — Timezone Utilities
//
// Uses Intl.DateTimeFormat to extract correct wall-clock parts
// in the target timezone. Avoids the Date(toLocaleString()) anti-pattern
// which can be off by ±1 hour near DST transitions.
// ============================================================

const TZ = process.env.NEXT_PUBLIC_TIMEZONE || "Asia/Singapore";

// Reusable formatters (allocated once per TZ, cached by the engine)
const partFormatter = new Intl.DateTimeFormat("en-US", {
  timeZone: TZ,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

/**
 * Return an object with the wall-clock parts in the configured timezone.
 * This is the correct way to extract tz-adjusted components.
 */
function tzParts(date: Date = new Date()): Record<string, string> {
  const parts: Record<string, string> = {};
  for (const { type, value } of partFormatter.formatToParts(date)) {
    parts[type] = value;
  }
  return parts;
}

/**
 * Return the current hour in the configured timezone (0–23).
 * Used by sessionLabel() and callers that only need the hour.
 */
export function nowHourInTz(): number {
  const p = tzParts();
  return parseInt(p.hour, 10);
}

/**
 * Return a Date whose UTC fields equal the wall-clock in TZ.
 * Useful when you need a Date object for display calculations
 * but ONLY use getUTC*() methods on the result.
 *
 * @deprecated Prefer nowHourInTz() or formatTime/formatDate directly.
 */
export function nowInTz(): Date {
  const p = tzParts();
  return new Date(
    Date.UTC(
      parseInt(p.year, 10),
      parseInt(p.month, 10) - 1,
      parseInt(p.day, 10),
      parseInt(p.hour, 10),
      parseInt(p.minute, 10),
      parseInt(p.second, 10),
    ),
  );
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

/**
 * Format a timestamp as a short locale date in the configured timezone.
 * e.g. "15 Jan, 2024"
 *
 * Named `formatLocalDate` to distinguish from `formatDate` in `@/lib/formatters`
 * (which outputs UTC ISO-style strings for SSR-safe audit/log display).
 */
export function formatLocalDate(ts: number | string | Date, tz = TZ): string {
  const d = typeof ts === "object" ? ts : new Date(ts);
  return d.toLocaleDateString("en-US", {
    timeZone: tz,
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

/**
 * Format a timestamp as a locale datetime string in the configured timezone.
 * e.g. "15 Jan, 2024 14:30:45"
 *
 * Named `formatLocalDateTime` to distinguish from `formatDateTime` in `@/lib/formatters`
 * (which outputs UTC ISO-style strings for SSR-safe audit/log display).
 */
export function formatLocalDateTime(ts: number | string | Date, tz = TZ): string {
  return `${formatLocalDate(ts, tz)} ${formatTime(ts, tz)}`;
}

/** @deprecated Use formatLocalDate — avoids confusion with formatters.formatDate (UTC) */
export const formatDate = formatLocalDate;
/** @deprecated Use formatLocalDateTime — avoids confusion with formatters.formatDateTime (UTC) */
export const formatDateTime = formatLocalDateTime;

export function sessionLabel(): string {
  const h = nowHourInTz();
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
