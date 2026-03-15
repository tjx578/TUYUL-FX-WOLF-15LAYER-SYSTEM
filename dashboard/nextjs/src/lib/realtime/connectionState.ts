/**
 * Shared connection state types and stale threshold config per domain.
 *
 * Stale thresholds define how long (ms) a domain can go without a new
 * WS message before it transitions to STALE state in the UI.
 */

export type WsConnectionStatus =
  | "CONNECTING"
  | "LIVE"
  | "DEGRADED"
  | "RECONNECTING"
  | "STALE"
  | "DISCONNECTED";

export const STALE_THRESHOLDS_MS: Record<string, number> = {
  prices: 3000,   // aggressive — prices should tick every second
  trades: 8000,
  risk: 10000,
  equity: 10000,
  signals: 15000,
  verdicts: 15000,
  pipeline: 15000,
  candles: 1500,  // candle aggregator pushes every 500ms
  alerts: 30000,  // alerts are event-driven, not periodic
} as const;
