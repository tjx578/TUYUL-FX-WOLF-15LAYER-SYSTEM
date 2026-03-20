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
  prices: 5000,     // tick data — should arrive frequently
  trades: 10000,    // trade events
  risk: 15000,      // risk updates
  equity: 15000,    // equity snapshots
  signals: 90000,   // analysis loop = 60s + buffer
  verdicts: 90000,  // verdict updates follow analysis loop
  pipeline: 90000,  // pipeline results follow analysis loop
  candles: 20000,   // candle close events (M15 = every 15 min, but partial updates more frequent)
  alerts: 60000,    // alerts are event-driven
} as const;
