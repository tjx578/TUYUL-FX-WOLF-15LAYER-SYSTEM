import { format, parseISO } from 'date-fns-tz';
import { toZonedTime } from 'date-fns-tz';

// Declare process type for environments without Node.js types
declare const process: {
  env: { [key: string]: string | undefined };
} | undefined;

let SYSTEM_TZ: string = 'Asia/Singapore';

if (typeof window === 'undefined') {
  // Server-side: use process.env if available
  if (typeof process !== 'undefined' && process.env.NEXT_PUBLIC_TIMEZONE) {
    SYSTEM_TZ = process.env.NEXT_PUBLIC_TIMEZONE;
  }
} else {
  // Client-side: use window variable if available
  if ((window as any).NEXT_PUBLIC_TIMEZONE) {
    SYSTEM_TZ = (window as any).NEXT_PUBLIC_TIMEZONE;
  }
}

// Validate timezone on module load
try {
  toZonedTime(new Date(), SYSTEM_TZ);
} catch (error) {
  console.error(`Invalid timezone configured: ${SYSTEM_TZ}. Falling back to UTC.`);
  // Module will use UTC as fallback
}

/**
 * Format UTC timestamp to local timezone (GMT+8)
 */
export function formatLocalTime(utcTimestamp: string | Date): string {
  try {
    const date = typeof utcTimestamp === 'string' ? parseISO(utcTimestamp) : utcTimestamp;
    const zonedDate = toZonedTime(date, SYSTEM_TZ);
    return format(zonedDate, 'yyyy-MM-dd HH:mm:ss');
  } catch (error) {
    console.error('Error formatting local time:', error);
    return 'Invalid time';
  }
}

/**
 * Format UTC timestamp
 */
export function formatUTCTime(utcTimestamp: string | Date): string {
  try {
    const date = typeof utcTimestamp === 'string' ? parseISO(utcTimestamp) : utcTimestamp;
    return format(date, 'yyyy-MM-dd HH:mm:ss');
  } catch (error) {
    console.error('Error formatting UTC time:', error);
    return 'Invalid time';
  }
}

/**
 * Get current time in local timezone
 */
export function getCurrentLocalTime(): string {
  const now = new Date();
  const zonedDate = toZonedTime(now, SYSTEM_TZ);
  return format(zonedDate, 'yyyy-MM-dd HH:mm:ss');
}

/**
 * Get current time in UTC
 */
export function getCurrentUTCTime(): string {
  return format(new Date(), 'yyyy-MM-dd HH:mm:ss');
}

/**
 * Format time for display (HH:mm:ss)
 */
export function formatTimeOnly(utcTimestamp: string | Date): string {
  try {
    const date = typeof utcTimestamp === 'string' ? parseISO(utcTimestamp) : utcTimestamp;
    const zonedDate = toZonedTime(date, SYSTEM_TZ);
    return format(zonedDate, 'HH:mm:ss');
  } catch (error) {
    return '--:--:--';
  }
}
