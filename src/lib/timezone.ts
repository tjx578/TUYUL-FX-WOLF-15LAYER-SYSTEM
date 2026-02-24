import { format, toZonedTime } from 'date-fns-tz';
import { parseISO } from 'date-fns';

export const DEFAULT_TIMEZONE =
  process.env.NEXT_PUBLIC_DEFAULT_TIMEZONE || "Asia/Jakarta";

export function isoToZonedDate(
  isoString: string,
  timeZone: string = DEFAULT_TIMEZONE
): Date {
  return utcToZonedTime(parseISO(isoString), timeZone);
}

export function formatIsoInTimeZone(
  isoString: string,
  formatStr: string = "yyyy-MM-dd HH:mm:ss",
  timeZone: string = DEFAULT_TIMEZONE
): string {
  return formatInTimeZone(parseISO(isoString), timeZone, formatStr);
}

export function formatDateInTimeZone(
  date: Date,
  formatStr: string = "yyyy-MM-dd HH:mm:ss",
  timeZone: string = DEFAULT_TIMEZONE
): string {
  return formatInTimeZone(date, timeZone, formatStr);
}