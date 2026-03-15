/**
 * TUYUL FX Wolf-15 — Realtime module barrel export
 *
 * Import domain hooks from here:
 *   import { useLivePrices } from "@/lib/realtime";
 *   import { useLiveTrades } from "@/lib/realtime";
 *   import { useLiveRisk }   from "@/lib/realtime";
 *   import { useLiveSignals } from "@/lib/realtime";
 *
 * Import low-level client only if you're building a new domain adapter:
 *   import { connectLiveUpdates } from "@/lib/realtime/realtimeClient";
 */

export { connectLiveUpdates } from "./realtimeClient";
export type { WsConnectionStatus, WsControls } from "./realtimeClient";
export { STALE_THRESHOLDS_MS } from "./connectionState";
export { mergeMap, mergeSingle, mergeList } from "./merge";
export { useLivePrices } from "./hooks/useLivePrices";
export { useLiveTrades } from "./hooks/useLiveTrades";
export { useLiveRisk } from "./hooks/useLiveRisk";
export { useLiveSignals } from "./hooks/useLiveSignals";
