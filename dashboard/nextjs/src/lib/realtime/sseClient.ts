/**
 * TUYUL FX Wolf-15 — SSE (Server-Sent Events) Client
 *
 * Fallback transport when WebSocket is unavailable.
 * One-way server→client streaming via standard EventSource API.
 *
 * Sits between WebSocket (optimal) and REST polling (last resort)
 * in the transport fallback chain.
 */

import { getTransportToken } from "@/lib/auth";
import { getApiBaseUrl } from "@/lib/env";

export interface SseControls {
    close: () => void;
}

interface ConnectSseOptions {
    /** SSE endpoint path, e.g. "/api/v1/stream/live" */
    path: string;
    onMessage: (data: Record<string, unknown>) => void;
    onOpen?: () => void;
    onError?: (error: Event) => void;
}

/**
 * Open an SSE connection to the given path.
 *
 * Auth token is attached as a query parameter (same pattern as WS).
 * EventSource handles reconnect natively (browser auto-retries on disconnect).
 */
export function connectSse(options: ConnectSseOptions): SseControls {
    const { path, onMessage, onOpen, onError } = options;

    const baseUrl = getApiBaseUrl();
    const token = getTransportToken();
    const url = token
        ? `${baseUrl}${path}?token=${token}`
        : `${baseUrl}${path}`;

    const source = new EventSource(url);

    source.onopen = () => {
        if (process.env.NODE_ENV === "development") {
            console.debug(`[SSE] CONNECTED path=${path} ts=${new Date().toISOString()}`);
        }
        onOpen?.();
    };

    source.onmessage = (event) => {
        try {
            const parsed = JSON.parse(event.data as string);
            onMessage(parsed);
        } catch {
            // Ignore malformed messages
        }
    };

    source.onerror = (event) => {
        if (process.env.NODE_ENV === "development") {
            console.debug(`[SSE] ERROR path=${path} readyState=${source.readyState} ts=${new Date().toISOString()}`);
        }
        onError?.(event);
    };

    return {
        close: () => {
            source.close();
            if (process.env.NODE_ENV === "development") {
                console.debug(`[SSE] CLOSED path=${path} ts=${new Date().toISOString()}`);
            }
        },
    };
}
