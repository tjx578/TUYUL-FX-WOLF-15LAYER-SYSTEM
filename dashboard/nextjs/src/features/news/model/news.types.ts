/**
 * News / Economic Calendar domain types.
 *
 * Core data shapes (CalendarEvent, CalendarDayResponse, etc.) live in
 * the shared @/types barrel and are consumed via direct import there.
 * This file holds domain-local UI types that don't belong in the global barrel.
 */

/** Impact severity levels used for badge colours and filter controls. */
export type ImpactLevel = "HIGH" | "MEDIUM" | "LOW";

/** Style descriptor for impact badges. */
export interface ImpactStyle {
    bg: string;
    color: string;
    cls: string;
}

/** Static impact → style map. */
export const IMPACT_STYLES: Record<ImpactLevel, ImpactStyle> = {
    HIGH: { bg: "var(--red-glow)", color: "var(--red)", cls: "badge-red" },
    MEDIUM: { bg: "var(--yellow-glow)", color: "var(--yellow)", cls: "badge-yellow" },
    LOW: { bg: "rgba(68,138,255,0.12)", color: "var(--blue)", cls: "badge-blue" },
};

/** Filter options for the impact control bar. */
export const IMPACT_FILTERS = ["ALL", "HIGH", "MEDIUM", "LOW"] as const;

/** Currency options for the currency filter dropdown. */
export const CURRENCY_OPTIONS = [
    "ALL", "USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD",
] as const;
