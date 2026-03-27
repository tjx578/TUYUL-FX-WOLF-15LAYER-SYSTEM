/**
 * TUYUL FX Wolf-15 — Realtime Connection Multiplexer
 *
 * Maintains a SINGLE realtime connection and fans out events to all
 * registered subscribers. Transport fallback chain:
 *
 *   1. WebSocket (/ws/live)  — full-duplex, preferred
 *   2. SSE (/sse/live)       — uni-directional, works through Vercel/CDN
 *   3. REST polling           — last resort after 30s of WS+SSE failure
 *
 * Usage (in domain hooks):
 *   const unsub = subscribe({
 *     filter: (e) => e.type === "PriceUpdated" || e.type === "PricesSnapshot",
 *     onEvent:  (e) => { ... },
 *     onStatusChange: (s) => { ... },
 *   });
 *   // On cleanup:
 *   unsub();
 *
 * Lifecycle:
 *   - First subscriber triggers connection (WS first).
 *   - If WS URL not configured → skip SSE, go straight to REST polling (~500ms).
 *   - If WS configured but fails → try SSE after 30s (1 retry max).
 *   - SSE DEGRADED → REST polling fallback.
 *   - Last subscriber leaving closes all transports.
 *
 * For custom event types not in WsEventSchema (e.g. trade desk events),
 * use the `onRawMessage` callback which fires before Zod validation.
 */

import { connectLiveUpdates, type WsControls, type WsConnectionStatus } from "./realtimeClient";
import { connectSse, type SseControls } from "./sseClient";
import { getApiBaseUrl, getWsBaseUrl, getRestPrefix } from "@/lib/env";
import type { WsEventParsed } from "@/schema/wsEventSchema";
import type { SystemStatusView } from "@/contracts/wsEvents";

// ─── TRANSPORT LAYER ─────────────────────────────────────────

export type TransportMode = "WS" | "SSE" | "POLLING" | "NONE";

export interface TransportDiagnostics {
    transport: TransportMode;
    status: WsConnectionStatus;
    reason: string;
    wsFailedForMs: number;
    lastPollingHeartbeatAt: number | null;
}

// ─── TYPES ───────────────────────────────────────────────────

export interface MultiplexerSubscribeOptions {
    /** If provided, only matching events are forwarded to onEvent. */
    filter?: (event: WsEventParsed) => boolean;
    onEvent?: (event: WsEventParsed) => void;
    /** Fires for every raw JSON message before Zod validation. */
    onRawMessage?: (data: Record<string, unknown>) => void;
    onStatusChange?: (status: WsConnectionStatus) => void;
    onDegradation?: (status: SystemStatusView) => void;
    onSeqGap?: (missed: number) => void;
    onError?: (error: unknown) => void;
}

// ─── STATE ───────────────────────────────────────────────────

let wsConnection: WsControls | null = null;
let sseConnection: SseControls | null = null;
let currentStatus: WsConnectionStatus = "DISCONNECTED";
let currentTransport: TransportMode = "NONE";
let subscriberCounter = 0;
const subscribers = new Map<number, MultiplexerSubscribeOptions>();
let lastReason = "Realtime channel not initialized yet.";

// SSE fallback timer: triggers SSE after 30s of WS failure.
// When WS is known-unavailable (NEXT_PUBLIC_WS_BASE_URL not set), the delay
// is skipped entirely so the client reaches polling fallback within seconds.
const SSE_FALLBACK_DELAY_MS = 30_000;
const SSE_INSTANT_FALLBACK_MS = 500; // used when WS is known-unavailable
let sseFallbackTimer: ReturnType<typeof setTimeout> | null = null;
let wsFailedAt: number | null = null;
let wsOpenedAt: number | null = null; // tracks when WS was opened to detect instant failure

// Polling fallback (health heartbeat) — used when WS + SSE are down.
// Uses exponential backoff when the server responds with 429.
const POLLING_BASE_MS = 10_000;
const POLLING_MAX_BACKOFF_MS = 120_000;
let pollingBackoffMs = POLLING_BASE_MS;
let pollingTimer: ReturnType<typeof setTimeout> | null = null;
let pollingActive = false;
let lastPollingHeartbeatAt: number | null = null;

// Circuit breaker for polling: stop hammering /health after repeated 429s.
const POLLING_CIRCUIT_OPEN_AFTER = 3;   // consecutive 429s before circuit opens
const POLLING_CIRCUIT_RESET_MS = 60_000; // reopen circuit after 60s
let _pollingConsecutive429s = 0;
let _pollingCircuitOpenAt: number | null = null;

// ─── INTERNAL: FAN-OUT HELPERS ───────────────────────────────

function fanOutEvent(event: WsEventParsed): void {
    for (const sub of subscribers.values()) {
        if (!sub.filter || sub.filter(event)) {
            sub.onEvent?.(event);
        }
    }
}

function fanOutRaw(data: Record<string, unknown>): void {
    for (const sub of subscribers.values()) {
        sub.onRawMessage?.(data);
    }
}

function fanOutStatus(status: WsConnectionStatus): void {
    currentStatus = status;
    for (const sub of subscribers.values()) {
        sub.onStatusChange?.(status);
    }
}

function fanOutDegradation(status: SystemStatusView): void {
    lastReason = status.reason || lastReason;
    for (const sub of subscribers.values()) {
        sub.onDegradation?.(status);
    }
}

function fanOutSeqGap(missed: number): void {
    for (const sub of subscribers.values()) {
        sub.onSeqGap?.(missed);
    }
}

function fanOutError(error: unknown): void {
    for (const sub of subscribers.values()) {
        sub.onError?.(error);
    }
}

// ─── INTERNAL: TRANSPORT MANAGEMENT ──────────────────────────

function clearSseFallbackTimer(): void {
    if (sseFallbackTimer) {
        clearTimeout(sseFallbackTimer);
        sseFallbackTimer = null;
    }
    wsFailedAt = null;
}

function closeSseTransport(): void {
    if (sseConnection) {
        sseConnection.close();
        sseConnection = null;
    }
}

function stopPollingFallback(): void {
    pollingActive = false;
    if (pollingTimer) {
        clearTimeout(pollingTimer);
        pollingTimer = null;
    }
    pollingBackoffMs = POLLING_BASE_MS;
}

function startPollingFallback(): void {
    if (pollingActive) return;

    pollingActive = true;
    currentTransport = "POLLING";
    fanOutStatus("DEGRADED");
    fanOutDegradation({
        mode: "POLLING",
        reason: "WS + SSE unavailable. Running HTTP heartbeat polling with backoff.",
    });

    const tick = async () => {
        // Circuit breaker: skip tick if circuit is open (too many 429s).
        if (_pollingCircuitOpenAt !== null) {
            if (Date.now() - _pollingCircuitOpenAt < POLLING_CIRCUIT_RESET_MS) {
                return; // circuit still open — wait for reset window
            }
            // Reset circuit after cooling down
            _pollingCircuitOpenAt = null;
            _pollingConsecutive429s = 0;
        }
        if (!pollingActive) return;

        try {
            const t0 = Date.now();
            const prefix = getRestPrefix();
            const res = await fetch(`${prefix}/health`, { credentials: "include" });
            const latency = Date.now() - t0;

            if (res.status === 429) {
                _pollingConsecutive429s++;
                if (_pollingConsecutive429s >= POLLING_CIRCUIT_OPEN_AFTER) {
                    _pollingCircuitOpenAt = Date.now();
                    fanOutStatus("DEGRADED");
                    fanOutDegradation({
                        mode: "POLLING",
                        reason: `Rate-limited (429) by backend ${_pollingConsecutive429s} times. Pausing polling for ${POLLING_CIRCUIT_RESET_MS / 1000}s.`,
                    });
                }
                return;
            }

            _pollingConsecutive429s = 0;

            if (!res.ok) {
                pollingBackoffMs = Math.min(pollingBackoffMs * 2, POLLING_MAX_BACKOFF_MS);
                fanOutStatus("STALE");
                fanOutDegradation({
                    mode: "POLLING",
                    reason: `Polling heartbeat failed: /health returned HTTP ${res.status}.`,
                });
            } else {
                // Successful response — reset backoff
                pollingBackoffMs = POLLING_BASE_MS;
                lastPollingHeartbeatAt = Date.now();
                fanOutStatus("DEGRADED");
                fanOutDegradation({
                    mode: "POLLING",
                    reason: `Polling heartbeat OK (${latency}ms). Streaming transport still unavailable.`,
                });
            }
        } catch (err) {
            pollingBackoffMs = Math.min(pollingBackoffMs * 2, POLLING_MAX_BACKOFF_MS);
            fanOutStatus("STALE");
            fanOutDegradation({
                mode: "POLLING",
                reason: `Polling heartbeat failed: ${err instanceof Error ? err.message : "network error"}.`,
            });
        }

        // Schedule the next tick only if polling is still active
        if (pollingActive) {
            pollingTimer = setTimeout(tick, pollingBackoffMs);
        }
    };

    const scheduleTick = () => {
        pollingTimer = setTimeout(() => {
            void tick().then(scheduleTick);
        }, pollingBackoffMs);
    };
    void tick().then(scheduleTick);
}

function openSseConnection(): void {
    if (sseConnection) return;

    if (process.env.NODE_ENV === "development") {
        console.debug("[MUX] WS failed for 30s — activating SSE fallback");
    }

    currentTransport = "SSE";

    sseConnection = connectSse({
        path: "/sse/live",
        onEvent: fanOutEvent,
        onRawMessage: fanOutRaw,
        onStatusChange: (status) => {
            if (status === "LIVE") {
                stopPollingFallback();
                // SSE is working — update status to LIVE
                fanOutStatus("LIVE");
                fanOutDegradation({ mode: "SSE", reason: "Connected via SSE fallback" });
            } else if (status === "DEGRADED") {
                // SSE also failed — signal DEGRADED for REST polling fallback
                startPollingFallback();
            }
        },
        onDegradation: fanOutDegradation,
        onError: fanOutError,
    });
}

function startSseFallbackTimer(): void {
    if (sseFallbackTimer) return; // already scheduled
    if (sseConnection) return; // SSE already active

    wsFailedAt = Date.now();

    // Detect instant WS failure: if WS disconnected within 1s of opening, the
    // URL is likely not configured (empty wsBaseUrl) or unreachable.
    const wsAgeMs = wsOpenedAt ? (Date.now() - wsOpenedAt) : Infinity;
    const wsKnownUnavailable = !getWsBaseUrl();

    // When WS is known-unavailable (no NEXT_PUBLIC_WS_BASE_URL), the backend
    // also won't have an SSE endpoint (/sse/live doesn't exist yet). Skip
    // the SSE transport entirely and go straight to REST polling.
    if (wsKnownUnavailable) {
        sseFallbackTimer = setTimeout(() => {
            sseFallbackTimer = null;
            if (currentStatus !== "LIVE" && subscribers.size > 0) {
                if (process.env.NODE_ENV === "development") {
                    console.debug("[MUX] WS unavailable — skipping SSE, activating REST polling");
                }
                startPollingFallback();
            }
        }, SSE_INSTANT_FALLBACK_MS);
        return;
    }

    const delay = wsAgeMs < 1000
        ? SSE_INSTANT_FALLBACK_MS
        : SSE_FALLBACK_DELAY_MS;

    sseFallbackTimer = setTimeout(() => {
        sseFallbackTimer = null;
        // Only activate SSE if WS is still not LIVE
        if (currentStatus !== "LIVE" && subscribers.size > 0) {
            openSseConnection();
        }
    }, delay);
}

function openWsConnection(): void {
    if (wsConnection) return;

    currentTransport = "WS";
    wsOpenedAt = Date.now();

    wsConnection = connectLiveUpdates({
        path: "/ws/live",
        onEvent: fanOutEvent,
        onRawMessage: fanOutRaw,
        onStatusChange: (status) => {
            if (status === "LIVE") {
                // WS recovered — tear down SSE if it was active
                clearSseFallbackTimer();
                stopPollingFallback();
                if (sseConnection) {
                    closeSseTransport();
                    if (process.env.NODE_ENV === "development") {
                        console.debug("[MUX] WS recovered — SSE fallback closed");
                    }
                }
                currentTransport = "WS";
                fanOutStatus("LIVE");
            } else if (status === "DISCONNECTED" || status === "DEGRADED") {
                // WS failed — start SSE fallback timer (30s)
                startSseFallbackTimer();
                fanOutStatus(status);
            } else {
                fanOutStatus(status);
            }
        },
        onDegradation: fanOutDegradation,
        onSeqGap: fanOutSeqGap,
        onError: fanOutError,
    });
}

function closeAllTransports(): void {
    clearSseFallbackTimer();
    stopPollingFallback();

    if (wsConnection) {
        wsConnection.close();
        wsConnection = null;
    }

    closeSseTransport();

    // Reset circuit breaker state on full transport teardown.
    _pollingConsecutive429s = 0;
    _pollingCircuitOpenAt = null;

    currentTransport = "NONE";
    currentStatus = "DISCONNECTED";
    wsOpenedAt = null;
}

// ─── PUBLIC API ──────────────────────────────────────────────

/**
 * Subscribe to the shared realtime connection (WS → SSE → polling fallback).
 * Returns an unsubscribe function — call it in useEffect cleanup.
 */
export function subscribe(options: MultiplexerSubscribeOptions): () => void {
    const id = ++subscriberCounter;
    subscribers.set(id, options);

    // Open websocket on first subscriber
    if (subscribers.size === 1) {
        openWsConnection();
    } else {
        // Notify new subscriber of current status immediately
        options.onStatusChange?.(currentStatus);
    }

    return () => {
        subscribers.delete(id);
        if (subscribers.size === 0) {
            closeAllTransports();
        }
    };
}

/**
 * Send a message through the shared WS connection (e.g. subscription filters).
 * No-op when transport is SSE or polling (uni-directional).
 */
export function send(payload: unknown): void {
    wsConnection?.send(payload);
}

/**
 * Current connection status.
 */
export function getStatus(): WsConnectionStatus {
    return currentStatus;
}

/**
 * Current active transport layer.
 */
export function getTransport(): TransportMode {
    return currentTransport;
}

export function getTransportDiagnostics(): TransportDiagnostics {
    return {
        transport: currentTransport,
        status: currentStatus,
        reason: lastReason,
        wsFailedForMs: wsFailedAt ? Date.now() - wsFailedAt : 0,
        lastPollingHeartbeatAt,
    };
}

/**
 * Force-close all transports and clear all subscribers.
 * Use on logout or when tearing down the app.
 */
export function closeAll(): void {
    closeAllTransports();
    subscribers.clear();
}
