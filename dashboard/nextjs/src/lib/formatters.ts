/**
 * Hydration-safe formatting utilities.
 *
 * These produce identical output on server (Node.js) and client (browser)
 * by using fixed "en-GB" locale and UTC timezone — no locale/timezone
 * mismatch between Vercel SSR and user's browser.
 */

// ── Date formatting ──────────────────────────────────────────

interface FormatDateOptions {
    showTime?: boolean;
    showSeconds?: boolean;
}

/**
 * Format a date string/number to a deterministic "DD Mon HH:MM" style.
 * Always uses en-GB + UTC so SSR and client produce the same string.
 */
export function formatDate(
    value: string | number | Date | null | undefined,
    opts?: FormatDateOptions,
): string {
    if (value == null) return "—";
    try {
        const d = typeof value === "number" && value < 1e12
            ? new Date(value * 1000) // Unix seconds
            : new Date(value as string | number);
        if (isNaN(d.getTime())) return "—";

        const parts: Intl.DateTimeFormatOptions = {
            day: "2-digit",
            month: "short",
            timeZone: "UTC",
        };
        if (opts?.showTime !== false) {
            parts.hour = "2-digit";
            parts.minute = "2-digit";
        }
        if (opts?.showSeconds) {
            parts.second = "2-digit";
        }
        return d.toLocaleString("en-GB", parts);
    } catch {
        return "—";
    }
}

/**
 * Format a full datetime (date + time + seconds) for audit/log views.
 */
export function formatDateTime(
    value: string | number | Date | null | undefined,
): string {
    if (value == null) return "—";
    try {
        const d = new Date(value as string | number);
        if (isNaN(d.getTime())) return "—";
        return d.toLocaleString("en-GB", {
            dateStyle: "short",
            timeStyle: "medium",
            timeZone: "UTC",
        });
    } catch {
        return "—";
    }
}

// ── Number / currency formatting ─────────────────────────────

/**
 * Format a number as USD currency string: "$1,234.56"
 * Uses fixed en-US locale for deterministic SSR output.
 */
export function formatCurrency(
    value: number | null | undefined,
    decimals = 2,
): string {
    if (value == null || isNaN(value)) return "—";
    return value.toLocaleString("en-US", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    });
}

/**
 * Format a number with locale-safe thousands separator (no decimals).
 * For display like "10,000" without currency symbol.
 */
export function formatNumber(
    value: number | null | undefined,
): string {
    if (value == null || isNaN(value)) return "—";
    return value.toLocaleString("en-US");
}

/**
 * Format a percentage: "12.34%"
 */
export function formatPercent(
    value: number | null | undefined,
    decimals = 2,
): string {
    if (value == null || isNaN(value)) return "—";
    return `${value.toFixed(decimals)}%`;
}
