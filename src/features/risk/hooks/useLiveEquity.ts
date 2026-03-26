/**
 * Re-export useLiveEquity from the shared realtime layer.
 * Keeps risk domain imports self-contained — consumers import from
 * `@/features/risk/hooks/useLiveEquity` instead of `@/lib/realtime`.
 */
export { useLiveEquity } from "@/lib/realtime";
