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
 *
 * Import the connection multiplexer for single-WS fan-out:
 *   import { subscribe, closeAll } from "@/lib/realtime/multiplexer";
 */

export { connectLiveUpdates } from "./realtimeClient";
export type { WsConnectionStatus, WsControls } from "./realtimeClient";
export { STALE_THRESHOLDS_MS } from "./connectionState";
export { mergeMap, mergeSingle, mergeList } from "./merge";
export { subscribe as muxSubscribe, send as muxSend, getStatus as muxGetStatus, closeAll as muxCloseAll } from "./multiplexer";
export type { MultiplexerSubscribeOptions } from "./multiplexer";
export { useLivePrices } from "./hooks/useLivePrices";
export { useLiveTrades } from "./hooks/useLiveTrades";
export { useLiveRisk } from "./hooks/useLiveRisk";
export { useLiveSignals } from "./hooks/useLiveSignals";
export { useFilteredSignals, filterSignals } from "./hooks/useFilteredSignals";
export type { SignalFilterOptions } from "./hooks/useFilteredSignals";
export { useSignalNotifications } from "./hooks/useSignalNotifications";
export { useLiveEquity } from "./hooks/useLiveEquity";
export { useLiveAlerts } from "./hooks/useLiveAlerts";
export { useLiveCandles } from "./hooks/useLiveCandles";
