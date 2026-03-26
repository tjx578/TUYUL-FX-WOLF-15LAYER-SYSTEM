/**
 * Hydration-safe formatters for TUYUL FX Dashboard.
 *
 * Problem: .toLocaleString() produces different output on
 * Vercel Node.js (server) vs browser (client, WIB timezone).
 * This causes React Error #418 (hydration mismatch).
 *
 * Solution: Deterministic formatters that produce identical
 * output on server and client. No locale-dependent APIs
 * during SSR — only after hydration via useEffect.
 *
 * Usage:
 *   import { formatDate, formatNumber, formatCurrency } from "@/lib/formatters";
 *
 *   // In JSX (safe for SSR):
 *   <span>{formatDate(timestamp)}</span>
 *   <span>{formatNumber(1234.56, 2)}</span>
 *   <span>{formatCurrency(1234.56)}</span>
 *
 *   // For locale-aware display (client-only):
 *   import { useClientDate, useClientNumber } from "@/lib/formatters";
 *   const formatted = useClientDate(timestamp);
 */

"use client";

import { useEffect, useState } from "react";

// ══════════════════════════════════════════════════════════════
// DETERMINISTIC FORMATTERS (SSR-safe, identical on server+client)
// ══════════════════════════════════════════════════════════════

/**
 * Format a date/timestamp to ISO-like string (SSR-safe).
 * Always produces the same output regardless of locale/timezone.
 */
export function formatDate(
    value: string | number | Date | null | undefined,
    options?: { showTime?: boolean; showSeconds?: boolean }
): string {
    if (value == null) return "—";

    const { showTime = true, showSeconds = false } = options ?? {};

    try {
        const d = value instanceof Date ? value : new Date(value);
        if (isNaN(d.getTime())) return "—";

        const yyyy = d.getUTCFullYear();
        const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
        const dd = String(d.getUTCDate()).padStart(2, "0");

        if (!showTime) return `${yyyy}-${mm}-${dd}`;

        const hh = String(d.getUTCHours()).padStart(2, "0");
        const min = String(d.getUTCMinutes()).padStart(2, "0");

        if (!showSeconds) return `${yyyy}-${mm}-${dd} ${hh}:${min} UTC`;

        const ss = String(d.getUTCSeconds()).padStart(2, "0");
        return `${yyyy}-${mm}-${dd} ${hh}:${min}:${ss} UTC`;
    } catch {
        return "—";
    }
}

/**
 * Format a full datetime (date + time + seconds) for audit/log views.
 * Thin wrapper over formatDate — keeps the same SSR-safe approach.
 */
export function formatDateTime(
    value: string | number | Date | null | undefined
): string {
    return formatDate(value, { showTime: true, showSeconds: true });
}

/**
 * Format a number with fixed decimal places and comma separators (SSR-safe).
 * No locale-dependent APIs — uses regex for thousand separators.
 */
export function formatNumber(
    value: number | string | null | undefined,
    decimals: number = 2,
    options?: { fallback?: string }
): string {
    const { fallback = "—" } = options ?? {};

    if (value == null) return fallback;

    const num = typeof value === "string" ? parseFloat(value) : value;
    if (isNaN(num)) return fallback;

    // Add thousand separators deterministically (same regex as formatCurrency)
    const [intPart, decPart] = num.toFixed(decimals).split(".");
    const withCommas = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");

    return decPart ? `${withCommas}.${decPart}` : withCommas;
}

/**
 * Format currency value (SSR-safe).
 * Uses $ prefix + fixed decimals. No locale-dependent formatting.
 */
export function formatCurrency(
    value: number | string | null | undefined,
    options?: { decimals?: number; currency?: string; fallback?: string }
): string {
    const { decimals = 2, currency = "$", fallback = "—" } = options ?? {};

    if (value == null) return fallback;

    const num = typeof value === "string" ? parseFloat(value) : value;
    if (isNaN(num)) return fallback;

    const sign = num < 0 ? "-" : "";
    const abs = Math.abs(num);

    // Add thousand separators deterministically
    const [intPart, decPart] = abs.toFixed(decimals).split(".");
    const withCommas = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");

    return `${sign}${currency}${withCommas}${decPart ? "." + decPart : ""}`;
}

/**
 * Format percentage (SSR-safe).
 */
export function formatPercent(
    value: number | string | null | undefined,
    decimals: number = 1,
    options?: { fallback?: string }
): string {
    const { fallback = "—" } = options ?? {};

    if (value == null) return fallback;

    const num = typeof value === "string" ? parseFloat(value) : value;
    if (isNaN(num)) return fallback;

    return `${num >= 0 ? "+" : ""}${num.toFixed(decimals)}%`;
}

/**
 * Format pips value (SSR-safe).
 */
export function formatPips(
    value: number | string | null | undefined,
    decimals: number = 1
): string {
    if (value == null) return "—";
    const num = typeof value === "string" ? parseFloat(value) : value;
    if (isNaN(num)) return "—";
    return `${num.toFixed(decimals)} pips`;
}

// ══════════════════════════════════════════════════════════════
// CLIENT-ONLY HOOKS (locale-aware, only after hydration)
// ══════════════════════════════════════════════════════════════

/**
 * Format date with user's locale (client-only, hydration-safe).
 *
 * Returns deterministic string during SSR, switches to
 * locale-aware format after hydration.
 *
 * Usage:
 *   const formatted = useClientDate(timestamp);
 *   return <span>{formatted}</span>;
 */
export function useClientDate(
    value: string | number | Date | null | undefined,
    options?: Intl.DateTimeFormatOptions
): string {
    const ssrValue = formatDate(value);
    const [display, setDisplay] = useState(ssrValue);

    useEffect(() => {
        if (value == null) return;
        try {
            const d = value instanceof Date ? value : new Date(value);
            if (isNaN(d.getTime())) return;

            const formatted = d.toLocaleString(
                "en-GB",
                options ?? {
                    year: "numeric",
                    month: "2-digit",
                    day: "2-digit",
                    hour: "2-digit",
                    minute: "2-digit",
                    timeZoneName: "short",
                }
            );
            setDisplay(formatted);
        } catch {
            // Keep SSR value
        }
    }, [value]);

    return display;
}

/**
 * Format number with user's locale (client-only, hydration-safe).
 */
export function useClientNumber(
    value: number | string | null | undefined,
    options?: Intl.NumberFormatOptions
): string {
    const ssrValue = formatNumber(value);
    const [display, setDisplay] = useState(ssrValue);

    useEffect(() => {
        if (value == null) return;
        const num = typeof value === "string" ? parseFloat(value) : value;
        if (isNaN(num)) return;

        try {
            setDisplay(num.toLocaleString(undefined, options));
        } catch {
            // Keep SSR value
        }
    }, [value]);

    return display;
}

/**
 * Format currency with user's locale (client-only, hydration-safe).
 */
export function useClientCurrency(
    value: number | string | null | undefined,
    currency: string = "USD"
): string {
    const ssrValue = formatCurrency(value);
    const [display, setDisplay] = useState(ssrValue);

    useEffect(() => {
        if (value == null) return;
        const num = typeof value === "string" ? parseFloat(value) : value;
        if (isNaN(num)) return;

        try {
            setDisplay(
                num.toLocaleString(undefined, {
                    style: "currency",
                    currency,
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                })
            );
        } catch {
            // Keep SSR value
        }
    }, [value]);

    return display;
}

// ══════════════════════════════════════════════════════════════
// HYDRATION-SAFE HOOKS
// ══════════════════════════════════════════════════════════════

/**
 * Returns `true` only after the component has hydrated on the client.
 * Use to guard locale-dependent rendering that would cause React #418.
 *
 * Usage:
 *   const hydrated = useHydrated();
 *   return <span>{hydrated ? liveValue : "—"}</span>;
 */
export function useHydrated(): boolean {
    const [hydrated, setHydrated] = useState(false);
    useEffect(() => { setHydrated(true); }, []);
    return hydrated;
}

/**
 * Hydration-safe replacement for `useState(Date.now())`.
 * Returns `0` during SSR (deterministic), then switches to
 * a live-updating `Date.now()` after hydration.
 *
 * @param intervalMs — update interval in ms (default: 1000)
 *
 * Usage:
 *   const now = useHydratedNow(1000);
 *   const age = now > 0 ? now - lastSeen : 0;
 */
export function useHydratedNow(intervalMs: number = 1000): number {
    const [now, setNow] = useState<number>(0);

    useEffect(() => {
        setNow(Date.now());
        const id = setInterval(() => setNow(Date.now()), intervalMs);
        return () => clearInterval(id);
    }, [intervalMs]);

    return now;
}

/**
 * Format an age in milliseconds to a human-readable string (SSR-safe).
 * e.g. 3500 → "3s", 125000 → "2m 5s"
 */
export function formatAge(ageMs: number): string {
    if (ageMs <= 0) return "0s";

    const totalSec = Math.floor(ageMs / 1000);
    if (totalSec < 60) return `${totalSec}s`;

    const min = Math.floor(totalSec / 60);
    const sec = totalSec % 60;
    if (min < 60) return sec > 0 ? `${min}m ${sec}s` : `${min}m`;

    const hr = Math.floor(min / 60);
    const remMin = min % 60;
    return remMin > 0 ? `${hr}h ${remMin}m` : `${hr}h`;
}
