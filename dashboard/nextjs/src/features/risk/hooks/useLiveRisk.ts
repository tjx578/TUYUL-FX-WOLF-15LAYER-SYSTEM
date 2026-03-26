/**
 * Re-export useLiveRisk from the shared realtime layer.
 * Keeps risk domain imports self-contained — consumers import from
 * `@/features/risk/hooks/useLiveRisk` instead of `@/lib/realtime`.
 */
export { useLiveRisk } from "@/lib/realtime";
