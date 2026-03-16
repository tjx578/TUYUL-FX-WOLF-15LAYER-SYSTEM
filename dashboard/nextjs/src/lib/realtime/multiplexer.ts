/**
 * TUYUL FX Wolf-15 — WebSocket Connection Multiplexer
 *
 * Maintains a SINGLE WebSocket connection to /ws/live and fans out events
 * to all registered subscribers. This eliminates the overhead of N parallel
 * WebSocket connections (one per domain hook).
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
 *   - First subscriber triggers connection to /ws/live.
 *   - Last subscriber leaving closes the connection.
 *   - New subscribers arriving while connected get current status immediately.
 *
 * For custom event types not in WsEventSchema (e.g. trade desk events),
 * use the `onRawMessage` callback which fires before Zod validation.
 */

import { connectLiveUpdates, type WsControls, type WsConnectionStatus } from "./realtimeClient";
import type { WsEventParsed } from "@/schema/wsEventSchema";
import type { SystemStatusView } from "@/contracts/wsEvents";

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

let connection: WsControls | null = null;
let currentStatus: WsConnectionStatus = "DISCONNECTED";
let subscriberCounter = 0;
const subscribers = new Map<number, MultiplexerSubscribeOptions>();

// ─── INTERNAL ────────────────────────────────────────────────

function openConnection(): void {
    if (connection) return;

    connection = connectLiveUpdates({
        path: "/ws/live",
        onEvent: (event) => {
            for (const sub of subscribers.values()) {
                if (!sub.filter || sub.filter(event)) {
                    sub.onEvent?.(event);
                }
            }
        },
        onRawMessage: (data) => {
            for (const sub of subscribers.values()) {
                sub.onRawMessage?.(data);
            }
        },
        onStatusChange: (status) => {
            currentStatus = status;
            for (const sub of subscribers.values()) {
                sub.onStatusChange?.(status);
            }
        },
        onDegradation: (status) => {
            for (const sub of subscribers.values()) {
                sub.onDegradation?.(status);
            }
        },
        onSeqGap: (missed) => {
            for (const sub of subscribers.values()) {
                sub.onSeqGap?.(missed);
            }
        },
        onError: (error) => {
            for (const sub of subscribers.values()) {
                sub.onError?.(error);
            }
        },
    });
}

// ─── PUBLIC API ──────────────────────────────────────────────

/**
 * Subscribe to the shared WebSocket connection.
 * Returns an unsubscribe function — call it in useEffect cleanup.
 */
export function subscribe(options: MultiplexerSubscribeOptions): () => void {
    const id = ++subscriberCounter;
    subscribers.set(id, options);

    // Open the connection on first subscriber
    if (subscribers.size === 1) {
        openConnection();
    } else {
        // Notify new subscriber of current status immediately
        options.onStatusChange?.(currentStatus);
    }

    return () => {
        subscribers.delete(id);
        if (subscribers.size === 0 && connection) {
            connection.close();
            connection = null;
            currentStatus = "DISCONNECTED";
        }
    };
}

/**
 * Send a message through the shared connection (e.g. subscription filters).
 */
export function send(payload: unknown): void {
    connection?.send(payload);
}

/**
 * Current connection status.
 */
export function getStatus(): WsConnectionStatus {
    return currentStatus;
}

/**
 * Force-close the shared connection and clear all subscribers.
 * Use on logout or when tearing down the app.
 */
export function closeAll(): void {
    connection?.close();
    connection = null;
    subscribers.clear();
    currentStatus = "DISCONNECTED";
}
