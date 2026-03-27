/**
 * TUYUL FX Wolf-15 — SSE (Server-Sent Events) Client
 *
 * Intermediate fallback transport when WebSocket is unavailable.
 * Fallback chain: WS → SSE → REST polling.
 *
 * SSE is uni-directional (server→client only) but works through HTTP/1.1
 * proxies, Vercel Edge, and CDNs that block WebSocket upgrades.
 *
 * Uses the same backend envelope format as WS (event_type + payload),
 * normalised via the shared EVENT_TYPE_MAP.
 *
 * The SSE endpoint is expected at /sse/live (mirroring /ws/live).
 */

import { WsEventSchema, type WsEventParsed } from "@/schema/wsEventSchema";
import type { SystemStatusView } from "@/contracts/wsEvents";
import { getTransportToken } from "@/lib/auth";
import { getApiBaseUrl, getRestPrefix } from "@/lib/env";
import type { WsConnectionStatus } from "./connectionState";

// ─── BACKEND ENVELOPE NORMALISATION (mirrors realtimeClient.ts) ──

const EVENT_TYPE_MAP: Record<string, string> = {
    "verdict.update": "VerdictUpdated",
    "verdict.snapshot": "VerdictSnapshot",
    "pipeline.update": "PipelineUpdated",
    "pipeline.result": "PipelineResultUpdated",
    "price.snapshot": "PricesSnapshot",
    "price.tick": "PriceUpdated",
    "risk.state": "RiskUpdated",
    "risk.updated": "RiskStateUpdated",
    "execution.state": "ExecutionStateUpdated",
    "system.status": "SystemStatusUpdated",
    "signals.update": "SignalUpdated",
    "trade.snapshot": "TradeSnapshot",
    "trade.update": "TradeUpdated",
    "candle.snapshot": "CandleSnapshot",
    "candle.forming": "CandleForming",
    "equity.update": "EquityUpdated",
    "live.heartbeat_state": "SystemStatusUpdated",
    "live.snapshot": "SystemStatusUpdated",
};

function normalizeEvent(raw: Record<string, unknown>): Record<string, unknown> {
    if (typeof raw.event_type === "string" && raw.payload !== undefined) {
        const mapped = EVENT_TYPE_MAP[raw.event_type] ?? raw.event_type;
        return { ...raw, type: mapped };
    }
    return raw;
}

// ─── SSE CONTROLS ────────────────────────────────────────────

export interface SseControls {
    close: () => void;
    readonly status: WsConnectionStatus;
}

// ─── SSE CLIENT OPTIONS ──────────────────────────────────────

export interface ConnectSseOptions {
    /** SSE endpoint path, e.g. "/sse/live" */
    path: string;
    onEvent: (event: WsEventParsed) => void;
    onError?: (error: unknown) => void;
    onStatusChange?: (status: WsConnectionStatus) => void;
    onDegradation?: (status: SystemStatusView) => void;
    onRawMessage?: (data: Record<string, unknown>) => void;
}

// ─── RECONNECT (on top of EventSource native retry) ──────────

const SSE_RECONNECT_BASE_MS = 2000;
const SSE_RECONNECT_CEILING_MS = 30000;
const SSE_MAX_RETRIES = 5;

// ─── CONNECT SSE ─────────────────────────────────────────────

export function connectSse(options: ConnectSseOptions): SseControls {
    const {
        path,
        onEvent,
        onError,
        onStatusChange,
        onDegradation,
        onRawMessage,
    } = options;

    let eventSource: EventSource | null = null;
    let reconnectAttempt = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let intentionallyClosed = false;
    let currentStatus: WsConnectionStatus = "DISCONNECTED";

    const emitStatus = (s: WsConnectionStatus) => {
        currentStatus = s;
        onStatusChange?.(s);
    };

    // Use getApiBaseUrl for direct connection, fall back to getRestPrefix for Vercel proxy
    const apiBase = getApiBaseUrl() || getRestPrefix();

    const connect = () => {
        if (intentionallyClosed) return;

        emitStatus("CONNECTING");

        // Auth token via query param (EventSource doesn't support custom headers)
        const token = getTransportToken();
        const params = new URLSearchParams();
        if (token) params.set("token", token);
        const qs = params.toString();
        const url = `${apiBase}${path}${qs ? `?${qs}` : ""}`;

        try {
            eventSource = new EventSource(url);
        } catch (err) {
            onError?.(err);
            scheduleReconnect();
            return;
        }

        eventSource.onopen = () => {
            if (intentionallyClosed) return;
            reconnectAttempt = 0;
            if (process.env.NODE_ENV === "development") {
                console.debug(`[SSE] CONNECTED path=${path} ts=${new Date().toISOString()}`);
            }
            emitStatus("LIVE");
        };

        // Default message handler (unnamed events)
        eventSource.onmessage = (msg) => {
            if (intentionallyClosed) return;
            handleSseData(msg.data);
        };

        // Named event handlers — backend may send typed SSE events
        for (const eventType of Object.keys(EVENT_TYPE_MAP)) {
            eventSource.addEventListener(eventType, ((evt: MessageEvent) => {
                if (intentionallyClosed) return;
                handleSseData(evt.data);
            }) as EventListener);
        }

        eventSource.onerror = () => {
            if (intentionallyClosed) return;
            if (process.env.NODE_ENV === "development") {
                console.debug(
                    `[SSE] ERROR path=${path} attempt=${reconnectAttempt} ts=${new Date().toISOString()}`,
                );
            }

            // Close the browser's auto-reconnecting EventSource — we manage retries ourselves
            eventSource?.close();

            if (reconnectAttempt >= SSE_MAX_RETRIES) {
                emitStatus("DEGRADED");
                onDegradation?.({
                    mode: "SSE",
                    reason: `SSE failed after ${SSE_MAX_RETRIES} retries. Falling back to REST polling.`,
                });
                return;
            }

            emitStatus("RECONNECTING");
            scheduleReconnect();
        };
    };

    const handleSseData = (raw: string) => {
        try {
            const parsed = JSON.parse(raw);

            // Skip heartbeats
            const msgType = parsed.type ?? parsed.event_type ?? "";
            if (msgType === "ping" || msgType === "heartbeat" || msgType === "pong") {
                return;
            }

            onRawMessage?.(parsed);

            const normalised = normalizeEvent(parsed);
            const result = WsEventSchema.safeParse(normalised);
            if (result.success) {
                onEvent(result.data);
                if (result.data.type === "SystemStatusUpdated") {
                    onDegradation?.(result.data.payload);
                }
            }
        } catch (err) {
            onError?.(err);
        }
    };

    const scheduleReconnect = () => {
        if (intentionallyClosed) return;
        if (reconnectTimer) clearTimeout(reconnectTimer);

        reconnectAttempt++;
        const delay = Math.min(
            SSE_RECONNECT_BASE_MS * 2 ** reconnectAttempt,
            SSE_RECONNECT_CEILING_MS,
        );
        reconnectTimer = setTimeout(connect, delay);
    };

    connect();

    return {
        close: () => {
            intentionallyClosed = true;
            if (reconnectTimer) clearTimeout(reconnectTimer);
            eventSource?.close();
            eventSource = null;
            emitStatus("DISCONNECTED");
        },
        get status() {
            return currentStatus;
        },
    };
}
