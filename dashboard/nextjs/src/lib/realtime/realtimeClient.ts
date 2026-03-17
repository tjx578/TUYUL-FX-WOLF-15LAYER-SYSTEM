/**
 * TUYUL FX Wolf-15 — Realtime Client
 *
 * Core WebSocket client abstraction with production-grade reconnect discipline:
 *   - Exponential backoff with jitter (1s → 30s ceiling)
 *   - Infinite retry with no hard attempt cap
 *   - Stale detection timer
 *   - Visibility-aware pause (tab hidden → reduce reconnect aggression)
 *   - Auth token attachment
 *   - Connection status machine
 *
 * DO NOT use raw WebSocket() directly in application code.
 * DO use domain hooks (useLivePrices, useLiveTrades, etc.) instead.
 */

import { WsEventSchema, type WsEventParsed } from "@/schema/wsEventSchema";
import type { SystemStatusView } from "@/contracts/wsEvents";
import { getTransportToken, fetchWsTicket } from "@/lib/auth";
import { getWsBaseUrl } from "@/lib/env";

// ─── BACKEND ENVELOPE NORMALISATION ──────────────────────────
// Backend _ws_event() uses `event_type` field; frontend schema discriminates on `type`.
// Map backend dotted event names → PascalCase type discriminators.

const EVENT_TYPE_MAP: Record<string, string> = {
  "verdict.update": "VerdictUpdated",
  "verdict.snapshot": "VerdictSnapshot",
  "pipeline.update": "PipelineUpdated",
  "price.snapshot": "PricesSnapshot",
  "price.tick": "PriceUpdated",
  "risk.state": "RiskUpdated",
  "signals.update": "SignalUpdated",
  "trade.snapshot": "TradeSnapshot",
  "trade.update": "TradeUpdated",
  "candle.snapshot": "CandleSnapshot",
  "candle.forming": "CandleForming",
  "equity.update": "EquityUpdated",
};

function normalizeWsEvent(raw: Record<string, unknown>): Record<string, unknown> {
  // Backend envelope has event_type + payload wrapper
  if (typeof raw.event_type === "string" && raw.payload !== undefined) {
    const mapped = EVENT_TYPE_MAP[raw.event_type] ?? raw.event_type;
    return { ...raw, type: mapped };
  }
  // Direct messages (ping, auth_error) already have `type`
  return raw;
}

// ─── CONNECTION STATUS MACHINE ───────────────────────────────

export type WsConnectionStatus =
  | "CONNECTING"
  | "LIVE"
  | "DEGRADED"
  | "RECONNECTING"
  | "STALE"
  | "DISCONNECTED";

export interface WsControls {
  close: () => void;
  send: (payload: unknown) => void;
  /** Number of sequence gaps detected since connection opened. */
  readonly gapCount: number;
}

// ─── RECONNECT CONFIG ────────────────────────────────────────

const RECONNECT_BASE_MS = 1000; // 1s
const RECONNECT_CEILING_MS = 30000; // 30s
const RECONNECT_JITTER_PCT = 0.25; // ±25%
const STALE_THRESHOLD_MS = 5000; // 5s no message → STALE

// ─── CLIENT OPTIONS ──────────────────────────────────────────

interface ConnectLiveUpdatesOptions {
  path: string;
  onEvent: (event: WsEventParsed) => void;
  onError?: (error: unknown) => void;
  onStatusChange?: (status: WsConnectionStatus) => void;
  onDegradation?: (status: SystemStatusView) => void;
  /** Fired when a monotonic seq gap is detected. Callers should re-fetch the
   *  full REST snapshot to fill the gap. `missed` = number of lost messages. */
  onSeqGap?: (missed: number) => void;
  /** Fired for every parsed JSON message before Zod validation.
   *  Useful for custom event types not in the WsEventSchema (e.g. trade desk events). */
  onRawMessage?: (data: Record<string, unknown>) => void;
}

// ─── CONNECT LIVE UPDATES ────────────────────────────────────

export function connectLiveUpdates(
  options: ConnectLiveUpdatesOptions
): WsControls {
  const { path, onEvent, onError, onStatusChange, onDegradation, onSeqGap, onRawMessage } = options;

  let socket: WebSocket | null = null;
  let reconnectAttempt = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let staleTimer: ReturnType<typeof setTimeout> | null = null;
  let intentionallyClosed = false;
  let lastMessageAt = Date.now();
  let visibilityPaused = false;

  // Monotonic sequence tracking for gap detection
  let lastSeq = 0;
  let gapCount = 0;

  const wsBaseUrl = getWsBaseUrl();
  if (!wsBaseUrl || wsBaseUrl.trim() === "") {
    onStatusChange?.("DISCONNECTED");
    onDegradation?.({
      mode: "DEGRADED",
      reason:
        "NEXT_PUBLIC_WS_BASE_URL not configured. Set it to your Railway wss:// origin.",
    });
    return { close: () => { }, send: () => { }, gapCount: 0 };
  }

  const connect = async () => {
    if (intentionallyClosed) return;
    if (visibilityPaused && reconnectAttempt > 3) return; // reduce churn when hidden

    onStatusChange?.(reconnectAttempt === 0 ? "CONNECTING" : "RECONNECTING");

    // Prefer synchronous JWT, fall back to server-side WS ticket
    const token = typeof window !== "undefined"
      ? (getTransportToken() ?? await fetchWsTicket())
      : null;
    const url = token ? `${wsBaseUrl}${path}?token=${token}` : `${wsBaseUrl}${path}`;

    try {
      socket = new WebSocket(url);
    } catch (err) {
      onError?.(err);
      scheduleReconnect();
      return;
    }

    socket.onopen = () => {
      if (intentionallyClosed) return;
      reconnectAttempt = 0;
      lastMessageAt = Date.now();
      // Reset seq tracking on fresh connection (server may have restarted)
      lastSeq = 0;
      if (process.env.NODE_ENV === "development") {
        console.debug(`[WS] CONNECTED path=${path} ts=${new Date().toISOString()}`);
      }
      onStatusChange?.("LIVE");
      startStaleTimer();
    };

    socket.onmessage = (msg) => {
      if (intentionallyClosed) return;
      lastMessageAt = Date.now();
      resetStaleTimer();

      try {
        const parsed = JSON.parse(msg.data as string);

        // ── Respond to server pings to keep heartbeat alive ──
        if (parsed.type === "ping") {
          if (socket?.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: "pong" }));
          }
          return;
        }

        // ── WS event type diagnostics ──
        if (process.env.NODE_ENV === "development") {
          const evtType = parsed.type ?? "UNKNOWN";
          const seq = typeof parsed.seq === "number" ? parsed.seq : "-";
          console.debug(`[WS] event=${evtType} seq=${seq} ts=${new Date().toISOString()}`);
        }

        // ── Fire raw handler before Zod validation ──
        onRawMessage?.(parsed);

        // ── Monotonic seq# gap detection ──
        const seq = typeof parsed.seq === "number" ? parsed.seq : 0;
        if (seq > 0) {
          if (lastSeq > 0 && seq !== lastSeq + 1) {
            const missed = seq - lastSeq - 1;
            gapCount++;
            onSeqGap?.(missed);
            onDegradation?.({
              mode: "DEGRADED",
              reason: `Sequence gap detected: expected ${lastSeq + 1}, got ${seq} (${missed} message(s) lost)`,
            });
          }
          lastSeq = seq;
        }

        // ── Safe parse: unknown event types are skipped, valid events pass through ──
        const normalised = normalizeWsEvent(parsed);
        const result = WsEventSchema.safeParse(normalised);
        if (result.success) {
          onEvent(result.data);
          if (result.data.type === "SystemStatusUpdated") {
            onDegradation?.(result.data.payload);
          }
        } else if (process.env.NODE_ENV === "development") {
          console.debug("[WS] Unknown/invalid event type, skipping:", normalised.type ?? parsed.type);
        }
      } catch (err) {
        onError?.(err);
      }
    };

    socket.onerror = () => {
      if (intentionallyClosed) return;
      onStatusChange?.("DEGRADED");
      onDegradation?.({
        mode: "DEGRADED",
        reason: "WebSocket connection error. Backend may be offline or unreachable.",
      });
    };

    socket.onclose = () => {
      if (intentionallyClosed) return;
      if (process.env.NODE_ENV === "development") {
        console.debug(`[WS] DISCONNECTED path=${path} attempt=${reconnectAttempt} ts=${new Date().toISOString()}`);
      }
      onStatusChange?.("DISCONNECTED");
      clearStaleTimer();
      scheduleReconnect();
    };
  };

  const scheduleReconnect = () => {
    if (intentionallyClosed) return;
    if (reconnectTimer) clearTimeout(reconnectTimer);

    reconnectAttempt++;
    const delay = calculateBackoff(reconnectAttempt);
    reconnectTimer = setTimeout(connect, delay);
  };

  const calculateBackoff = (attempt: number): number => {
    const raw = Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_CEILING_MS);
    const jitter = raw * RECONNECT_JITTER_PCT * (Math.random() * 2 - 1);
    return Math.max(RECONNECT_BASE_MS, raw + jitter);
  };

  const startStaleTimer = () => {
    clearStaleTimer();
    staleTimer = setTimeout(() => {
      if (intentionallyClosed) return;
      const elapsed = Date.now() - lastMessageAt;
      if (elapsed >= STALE_THRESHOLD_MS) {
        onStatusChange?.("STALE");
      }
    }, STALE_THRESHOLD_MS);
  };

  const resetStaleTimer = () => {
    clearStaleTimer();
    startStaleTimer();
  };

  const clearStaleTimer = () => {
    if (staleTimer) {
      clearTimeout(staleTimer);
      staleTimer = null;
    }
  };

  const handleVisibilityChange = () => {
    if (typeof document === "undefined") return;
    visibilityPaused = document.hidden;
    // If tab becomes visible and we're disconnected, try reconnect immediately
    if (!visibilityPaused && socket?.readyState !== WebSocket.OPEN) {
      reconnectAttempt = Math.max(0, reconnectAttempt - 2); // boost priority
      if (reconnectTimer) clearTimeout(reconnectTimer);
      scheduleReconnect();
    }
  };

  if (typeof document !== "undefined") {
    document.addEventListener("visibilitychange", handleVisibilityChange);
  }

  // Start initial connection
  connect();

  return {
    close: () => {
      intentionallyClosed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      clearStaleTimer();
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", handleVisibilityChange);
      }
      if (
        socket &&
        (socket.readyState === WebSocket.OPEN ||
          socket.readyState === WebSocket.CONNECTING)
      ) {
        socket.close();
      }
    },
    send: (payload: unknown) => {
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify(payload));
      }
    },
    get gapCount() {
      return gapCount;
    },
  };
}
