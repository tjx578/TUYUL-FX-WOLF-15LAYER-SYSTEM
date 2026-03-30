/**
 * TUYUL FX Wolf-15 — Realtime Client
 *
 * Core WebSocket client abstraction with production-grade reconnect discipline:
 *   - Per-message deflate compression (negotiated via Sec-WebSocket-Extensions)
 *   - Exponential backoff with jitter (1s → 30s ceiling)
 *   - Infinite retry with no hard attempt cap
 *   - Stale detection timer
 *   - Visibility-aware pause (tab hidden → reduce reconnect aggression)
 *   - Auth token attachment
 *   - Connection status machine
 *   - Proactive client heartbeat (keeps server-side heartbeat loop alive)
 *   - Sequence gap detection with auto-snapshot request
 *
 * DO NOT use raw WebSocket() directly in application code.
 * DO use domain hooks (useLivePrices, useLiveTrades, etc.) instead.
 */

import { WsEventSchema, type WsEventParsed } from "@/schema/wsEventSchema";
import type { SystemStatusView } from "@/contracts/wsEvents";
import { getTransportToken, fetchWsTicket } from "@/lib/auth";
import { getWsBaseUrl } from "@/lib/env";
import { STALE_THRESHOLDS_MS } from "@/lib/realtime/connectionState";

// ─── BACKEND ENVELOPE NORMALISATION ──────────────────────────
// Backend _ws_event() uses `event_type` field; frontend schema discriminates on `type`.
// Map backend dotted event names → PascalCase type discriminators.

const EVENT_TYPE_MAP: Record<string, string> = {
  // ── Verdict / Pipeline ──
  "verdict.update": "VerdictUpdated",
  "verdict.snapshot": "VerdictSnapshot",
  "pipeline.update": "PipelineUpdated",
  "pipeline.result": "PipelineResultUpdated", // [BACKWARD COMPAT] Backend uses pipeline.update
  // ── Prices ──
  "price.snapshot": "PricesSnapshot",
  "price.tick": "PriceUpdated",
  // ── Risk / Execution ──
  "risk.state": "RiskUpdated",
  "risk.updated": "RiskUpdated", // [BACKWARD COMPAT] Backend emits risk.state, maps to same target
  "execution.state": "ExecutionStateUpdated", // [BACKWARD COMPAT] Backend never emits this
  // ── System ──
  "system.status": "SystemStatusUpdated", // [BACKWARD COMPAT] Backend uses live.heartbeat_state/live.snapshot
  // ── Signals / Trades ──
  "signals.update": "SignalUpdated",
  "signals.snapshot": "SignalUpdated", // Backend sends signal snapshots
  "trade.snapshot": "TradeSnapshot",
  "trade.update": "TradeUpdated",
  // ── Alerts ──
  "alert.event": "AlertCreated", // Backend emits from /ws/alerts
  // ── Candles / Equity ──
  "candle.snapshot": "CandleSnapshot",
  "candle.forming": "CandleForming",
  "equity.update": "EquityUpdated",
  // ── TRQ (Trade Risk Quotient) ──
  "trq.snapshot": "TRQSnapshot",
  "trq.update": "TRQUpdated",
  // ── Live feed events ──
  "live.heartbeat_state": "SystemStatusUpdated",
  // live.snapshot carries {signals, accounts, trades} — NOT SystemStatus shape.
  // Let normalizeWsEvent handle it specially instead of mapping to SystemStatusUpdated.
  "live_event.heartbeat_state": "SystemStatusUpdated",
};

function normalizeWsEvent(raw: Record<string, unknown>): Record<string, unknown> {
  // Backend envelope has event_type + payload wrapper
  if (typeof raw.event_type === "string" && raw.payload !== undefined) {
    const eventType = raw.event_type as string;

    // live.snapshot carries {signals, accounts, trades} — not SystemStatus shape.
    // Convert to SystemStatusUpdated with derived metadata so the Zod schema passes.
    if (eventType === "live.snapshot") {
      const payload = raw.payload as Record<string, unknown> | undefined;
      const signalCount = Array.isArray(payload?.signals) ? payload.signals.length : 0;
      const accountCount = Array.isArray(payload?.accounts) ? payload.accounts.length : 0;
      return {
        ...raw,
        type: "SystemStatusUpdated",
        payload: {
          mode: signalCount > 0 ? "NORMAL" : "DEGRADED",
          reason: `live snapshot: ${signalCount} signals, ${accountCount} accounts`,
          updated_at: typeof raw.server_ts === "number"
            ? new Date(raw.server_ts * 1000).toISOString()
            : new Date().toISOString(),
        },
      };
    }

    const mapped = EVENT_TYPE_MAP[eventType] ?? eventType;
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
  /** Whether per-message deflate compression was negotiated. */
  readonly compressionActive: boolean;
}

// ─── RECONNECT CONFIG ────────────────────────────────────────

const RECONNECT_BASE_MS = 1000;
const RECONNECT_CEILING_MS = 30000;
const RECONNECT_JITTER_PCT = 0.25;

// 429 back-off: if the WS ticket fetch or upgrade itself gets rate-limited,
// pause reconnect for this duration before retrying.
const RATE_LIMIT_BACKOFF_MS = 60_000;

// [BUG FIX #9] Was 45000ms — still too low for analysis-driven messages
// (analysis loop = 60s).  Derive from per-domain thresholds in
// connectionState.ts so the global WS stale timer never fires before
// the slowest domain-specific timer.
const STALE_THRESHOLD_MS = Math.max(...Object.values(STALE_THRESHOLDS_MS));

// [BUG FIX #1] Proactive client heartbeat interval.
// Backend _heartbeat_loop checks for ANY client activity within its
// timeout window.  If client sends nothing, backend declares stale
// and disconnects.  This timer sends a pong every 10s to keep alive.
const CLIENT_HEARTBEAT_INTERVAL_MS = 10000;

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
  options: ConnectLiveUpdatesOptions,
): WsControls {
  const {
    path,
    onEvent,
    onError,
    onStatusChange,
    onDegradation,
    onSeqGap,
    onRawMessage,
  } = options;

  let socket: WebSocket | null = null;
  let reconnectAttempt = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let staleTimer: ReturnType<typeof setTimeout> | null = null;
  let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  let intentionallyClosed = false;
  let lastMessageAt = Date.now();
  let visibilityPaused = false;
  // [BUG FIX #6] Guard against async connect() racing with close()
  let connectAborted = false;
  // 429 rate-limit guard: timestamp when we should next allow a reconnect.
  let rateLimitedUntilMs = 0;
  // [BUG FIX #10] Minimum interval between connect attempts to prevent
  // fetchWsTicket() from exceeding backend WS_CONNECT_PER_MIN rate limit.
  let lastConnectAttemptAt = 0;
  const MIN_RECONNECT_INTERVAL_MS = 5000;

  // Monotonic sequence tracking for gap detection
  let lastSeq = 0;
  let gapCount = 0;
  // Track consecutive messages without gaps for DEGRADED recovery
  let consecutiveGoodMessages = 0;
  // Track current connection status for auto-recovery logic
  let currentStatus: WsConnectionStatus = "DISCONNECTED";
  // Per-message deflate compression state
  let compressionActive = false;

  /** Update status and notify caller. */
  const emitStatus = (s: WsConnectionStatus) => {
    currentStatus = s;
    onStatusChange?.(s);
  };

  const wsBaseUrl = getWsBaseUrl();
  if (!wsBaseUrl || wsBaseUrl.trim() === "") {
    emitStatus("DISCONNECTED");
    onDegradation?.({
      mode: "DEGRADED",
      reason:
        "NEXT_PUBLIC_WS_BASE_URL not configured. Set it to your Railway wss:// origin.",
    });
    return { close: () => { }, send: () => { }, gapCount: 0, compressionActive: false };
  }

  // ── Proactive client heartbeat ─────────────────────────────
  // [BUG FIX #1] Backend _heartbeat_loop measures time since last
  // client message.  If we only respond to server pings but the server
  // doesn't send pings (it just monitors), the client appears silent.
  // This interval proactively sends a lightweight pong every 10s so
  // the server always sees recent client activity.

  const startClientHeartbeat = () => {
    stopClientHeartbeat();
    heartbeatTimer = setInterval(() => {
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "pong" }));
      }
    }, CLIENT_HEARTBEAT_INTERVAL_MS);
  };

  const stopClientHeartbeat = () => {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer);
      heartbeatTimer = null;
    }
  };

  const connect = async () => {
    if (intentionallyClosed) return;
    if (visibilityPaused && reconnectAttempt > 3) return;

    // 429 rate-limit guard: defer connect until the back-off window expires.
    if (rateLimitedUntilMs > Date.now()) {
      const delay = rateLimitedUntilMs - Date.now();
      if (process.env.NODE_ENV === "development") {
        console.warn(`[WS] Rate-limited. Delaying reconnect by ${Math.round(delay / 1000)}s.`);
      }
      reconnectTimer = setTimeout(connect, delay);
      return;
    }
    // [BUG FIX #10] Throttle connect attempts to stay within rate limits
    const now = Date.now();
    const elapsed = now - lastConnectAttemptAt;
    if (elapsed < MIN_RECONNECT_INTERVAL_MS) {
      await new Promise(r => setTimeout(r, MIN_RECONNECT_INTERVAL_MS - elapsed));
      if (intentionallyClosed || connectAborted) return;
    }
    lastConnectAttemptAt = Date.now();

    connectAborted = false;
    emitStatus(reconnectAttempt === 0 ? "CONNECTING" : "RECONNECTING");

    // [BUG FIX #7+#8] Prefer WS ticket from server route (returns session
    // cookie or server-side API_KEY — never exposes key in client bundle).
    // Only fall back to localStorage JWT if the ticket fetch fails.
    // This ensures WS auth works even when the cached JWT lacks a role claim.
    let token: string | null = null;
    try {
      if (typeof window !== "undefined") {
        token = (await fetchWsTicket()) ?? getTransportToken();
      }
    } catch {
      // Ticket fetch failed (network error) — try localStorage JWT as last resort.
      token = getTransportToken();
    }

    // Guard: close() called while we were awaiting fetchWsTicket
    if (connectAborted || intentionallyClosed) return;

    const url = token
      ? `${wsBaseUrl}${path}?token=${token}`
      : `${wsBaseUrl}${path}`;

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
      lastSeq = 0;

      // ── Per-message deflate compression check ──
      // Browser negotiates permessage-deflate via Sec-WebSocket-Extensions
      // header during handshake. We verify it was accepted by the server.
      compressionActive = socket?.extensions?.includes("permessage-deflate") ?? false;
      if (process.env.NODE_ENV === "development") {
        console.debug(
          `[WS] CONNECTED path=${path} compression=${compressionActive ? "deflate" : "none"} ts=${new Date().toISOString()}`,
        );
        if (!compressionActive) {
          console.warn(
            "[WS] Per-message deflate NOT negotiated. Ensure server enables permessage-deflate extension for reduced payload sizes.",
          );
        }
      }

      emitStatus("LIVE");
      startStaleTimer();
      startClientHeartbeat();
    };

    socket.onmessage = (msg) => {
      if (intentionallyClosed) return;
      lastMessageAt = Date.now();
      resetStaleTimer();

      try {
        const parsed = JSON.parse(msg.data as string);

        // ── Respond to server pings to keep heartbeat alive ──
        // [BUG FIX #2] Check BOTH `type` AND `event_type` fields.
        // Backend may send ping as {"type":"ping"} or {"event_type":"ping"}.
        const msgType = parsed.type ?? parsed.event_type ?? "";
        if (
          msgType === "ping" ||
          msgType === "heartbeat" ||
          msgType === "pong"
        ) {
          if (socket?.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: "pong" }));
          }
          return;
        }

        // ── Ignore auth errors gracefully ──
        if (msgType === "auth_error") {
          const errMsg = parsed.message as string ?? "unknown";
          // Treat rate-limit responses embedded in WS auth errors as 429.
          if (typeof errMsg === "string" && (errMsg.includes("429") || errMsg.toLowerCase().includes("rate"))) {
            rateLimitedUntilMs = Date.now() + RATE_LIMIT_BACKOFF_MS;
          }
          onError?.(new Error(`WS auth error: ${errMsg}`));
          return;
        }

        // ── WS event type diagnostics ──
        if (process.env.NODE_ENV === "development") {
          const evtType = parsed.type ?? parsed.event_type ?? "UNKNOWN";
          const seq = typeof parsed.seq === "number" ? parsed.seq : "-";
          console.debug(
            `[WS] event=${evtType} seq=${seq} ts=${new Date().toISOString()}`,
          );
        }

        // ── Fire raw handler before Zod validation ──
        // This allows trade desk, candle, and signal hooks to process
        // events that are not (yet) in the WsEventSchema union.
        onRawMessage?.(parsed);

        // ── Monotonic seq# gap detection ──
        const seq = typeof parsed.seq === "number" ? parsed.seq : 0;
        if (seq > 0) {
          if (lastSeq > 0 && seq !== lastSeq + 1) {
            const missed = seq - lastSeq - 1;
            gapCount++;
            consecutiveGoodMessages = 0;
            onSeqGap?.(missed);
            // Only escalate to DEGRADED for significant gaps (>2 messages)
            if (missed > 2) {
              onDegradation?.({
                mode: "DEGRADED",
                reason: `Sequence gap detected: expected ${lastSeq + 1}, got ${seq} (${missed} message(s) lost)`,
              });
            }
          } else {
            consecutiveGoodMessages++;
          }
          lastSeq = seq;
        }

        // Auto-recover from DEGRADED when messages keep flowing
        if (currentStatus === "DEGRADED" || currentStatus === "STALE") {
          if (consecutiveGoodMessages >= 3) {
            emitStatus("LIVE");
            consecutiveGoodMessages = 0;
          }
        }

        // ── Normalise backend envelope → frontend discriminator ──
        const normalised = normalizeWsEvent(parsed);

        // ── Safe parse: unknown event types are skipped ──
        const result = WsEventSchema.safeParse(normalised);
        if (result.success) {
          onEvent(result.data);
          if (result.data.type === "SystemStatusUpdated") {
            onDegradation?.(result.data.payload);
          }
        } else if (process.env.NODE_ENV === "development") {
          console.debug(
            "[WS] Unknown/invalid event type, skipping:",
            normalised.type ?? parsed.event_type ?? parsed.type,
          );
        }
      } catch (err) {
        onError?.(err);
      }
    };

    socket.onerror = () => {
      if (intentionallyClosed) return;
      emitStatus("DEGRADED");
      onDegradation?.({
        mode: "DEGRADED",
        reason:
          "WebSocket connection error. Backend may be offline or unreachable.",
      });
    };

    socket.onclose = () => {
      if (intentionallyClosed) return;
      if (process.env.NODE_ENV === "development") {
        console.debug(
          `[WS] DISCONNECTED path=${path} attempt=${reconnectAttempt} ts=${new Date().toISOString()}`,
        );
      }
      emitStatus("DISCONNECTED");
      clearStaleTimer();
      stopClientHeartbeat();
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
    const raw = Math.min(
      RECONNECT_BASE_MS * 2 ** attempt,
      RECONNECT_CEILING_MS,
    );
    const jitter = raw * RECONNECT_JITTER_PCT * (Math.random() * 2 - 1);
    return Math.max(RECONNECT_BASE_MS, raw + jitter);
  };

  const startStaleTimer = () => {
    clearStaleTimer();
    staleTimer = setTimeout(() => {
      if (intentionallyClosed) return;
      const elapsed = Date.now() - lastMessageAt;
      if (elapsed >= STALE_THRESHOLD_MS) {
        emitStatus("STALE");
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
    if (!visibilityPaused && socket?.readyState !== WebSocket.OPEN) {
      reconnectAttempt = Math.max(0, reconnectAttempt - 2);
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
      connectAborted = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      clearStaleTimer();
      stopClientHeartbeat();
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
    get compressionActive() {
      return compressionActive;
    },
  };
}
