/**
 * TUYUL FX Dashboard — Fixed WebSocket Client
 *
 * PROBLEM:
 *   Original websocket.ts mengirim token via URL query (?token=xxx).
 *   Backend ws_auth.py mengecek token dari first message.
 *   Mismatch → 403 → dashboard tidak pernah terkoneksi.
 *
 * FIX:
 *   1. Message-based auth (send token as first message after connect)
 *   2. Handle auth_ok / auth_error responses
 *   3. Auto-reconnect with exponential backoff
 *   4. Typed event handlers for signals + pipeline status
 *
 * APPLY:
 *   Replace nextjs/src/lib/websocket.ts dengan file ini.
 */

// ── Types ───────────────────────────────────────────────────────────────────

export interface SignalData {
  pair: string;
  direction: "BUY" | "SELL" | "HOLD" | "NO_TRADE";
  entry: number;
  sl: number;
  tp1: number;
  tp2?: number;
  lots: number;
  wolf_score: string;
  grade: string;
  confidence: number;
  timestamp: string;
  layers?: Record<string, unknown>;
  gates?: Record<string, unknown>;
}

export interface PipelineStatus {
  pair: string;
  status: "running" | "idle" | "error" | "warmup";
  m15_bars: number;
  warmup_ok: boolean;
  feed_status: string;
  trading_allowed: boolean;
}

export interface WSMessage {
  type:
    | "auth_ok"
    | "auth_error"
    | "signal"
    | "pipeline_status"
    | "heartbeat"
    | "error";
  data?: unknown;
  channel?: string;
  role?: string;
  user_id?: string;
  reason?: string;
}

export type WSStatus = "connecting" | "authenticating" | "connected" | "disconnected" | "error";

export interface WSConfig {
  /** WebSocket URL (e.g., wss://backend.railway.app/ws) */
  url: string;
  /** JWT token for authentication */
  token: string;
  /** Called when a new signal arrives */
  onSignal?: (signal: SignalData) => void;
  /** Called when pipeline status updates */
  onStatus?: (status: PipelineStatus) => void;
  /** Called when connection status changes */
  onConnectionChange?: (status: WSStatus) => void;
  /** Called on any error */
  onError?: (error: string) => void;
  /** Max reconnect attempts (default: 10) */
  maxReconnectAttempts?: number;
}

// ── WebSocket Manager ───────────────────────────────────────────────────────

export class TuyulWebSocket {
  private ws: WebSocket | null = null;
  private config: WSConfig;
  private reconnectAttempts = 0;
  private maxReconnects: number;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private authenticated = false;
  private _status: WSStatus = "disconnected";

  constructor(config: WSConfig) {
    this.config = config;
    this.maxReconnects = config.maxReconnectAttempts ?? 10;
  }

  /** Current connection status */
  get status(): WSStatus {
    return this._status;
  }

  /** Connect to WebSocket server */
  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      console.warn("[WS] Already connected");
      return;
    }

    this.setStatus("connecting");

    try {
      // ✅ FIX: NO token in URL — clean connection
      this.ws = new WebSocket(this.config.url);
    } catch (e) {
      this.setStatus("error");
      this.config.onError?.(`Connection failed: ${e}`);
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      console.log("[WS] Connected, sending auth...");
      this.setStatus("authenticating");
      this.reconnectAttempts = 0;

      // ✅ FIX: Send token via first message (not URL query)
      this.ws?.send(
        JSON.stringify({
          type: "auth",
          token: this.config.token,
        })
      );
    };

    this.ws.onmessage = (event: MessageEvent) => {
      try {
        const msg: WSMessage = JSON.parse(event.data);
        this.handleMessage(msg);
      } catch (e) {
        console.error("[WS] Failed to parse message:", e);
      }
    };

    this.ws.onclose = (event: CloseEvent) => {
      console.log(`[WS] Closed: code=${event.code} reason=${event.reason}`);
      this.authenticated = false;

      if (event.code === 1000) {
        // Normal close — don't reconnect
        this.setStatus("disconnected");
      } else {
        this.setStatus("disconnected");
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = () => {
      console.error("[WS] Error occurred");
      this.setStatus("error");
      this.config.onError?.("WebSocket error");
    };
  }

  /** Disconnect cleanly */
  disconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.reconnectAttempts = this.maxReconnects; // prevent reconnect
    this.ws?.close(1000, "Client disconnect");
    this.ws = null;
    this.authenticated = false;
    this.setStatus("disconnected");
  }

  /** Update token (e.g., after refresh) and re-authenticate */
  updateToken(newToken: string): void {
    this.config.token = newToken;
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.disconnect();
      this.reconnectAttempts = 0;
      this.connect();
    }
  }

  // ── Private Methods ─────────────────────────────────────────────────────

  private handleMessage(msg: WSMessage): void {
    switch (msg.type) {
      case "auth_ok":
        console.log(`[WS] Authenticated as ${msg.role}`);
        this.authenticated = true;
        this.setStatus("connected");
        break;

      case "auth_error":
        console.error(`[WS] Auth failed: ${msg.reason}`);
        this.authenticated = false;
        this.setStatus("error");
        this.config.onError?.(`Auth failed: ${msg.reason}`);
        // Don't reconnect on auth errors — token is bad
        this.reconnectAttempts = this.maxReconnects;
        break;

      case "signal":
        if (msg.data && this.config.onSignal) {
          this.config.onSignal(msg.data as SignalData);
        }
        break;

      case "pipeline_status":
        if (msg.data && this.config.onStatus) {
          this.config.onStatus(msg.data as PipelineStatus);
        }
        break;

      case "heartbeat":
        // Server keepalive — no action needed
        break;

      case "error":
        console.error("[WS] Server error:", msg.reason);
        this.config.onError?.(msg.reason ?? "Unknown server error");
        break;

      default:
        console.log("[WS] Unknown message type:", msg.type);
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnects) {
      console.error(
        `[WS] Max reconnect attempts (${this.maxReconnects}) reached`
      );
      this.config.onError?.("Max reconnection attempts reached");
      return;
    }

    // Exponential backoff: 1s, 2s, 4s, 8s, 16s, max 30s
    const delay = Math.min(
      1000 * Math.pow(2, this.reconnectAttempts),
      30000
    );
    this.reconnectAttempts++;

    console.log(
      `[WS] Reconnecting in ${delay / 1000}s ` +
        `(attempt ${this.reconnectAttempts}/${this.maxReconnects})`
    );

    this.reconnectTimer = setTimeout(() => {
      this.connect();
    }, delay);
  }

  private setStatus(status: WSStatus): void {
    this._status = status;
    this.config.onConnectionChange?.(status);
  }
}

// ── React Hook ──────────────────────────────────────────────────────────────

/**
 * React hook for WebSocket connection.
 *
 * Usage:
 *   const { status, signals, pipelineStatus } = useWebSocket({
 *     url: process.env.NEXT_PUBLIC_WS_URL!,
 *     token: authToken,
 *   });
 */
// Note: Uncomment below if using React. Import useState, useEffect, useRef.
/*
import { useState, useEffect, useRef, useCallback } from "react";

export function useWebSocket(config: Omit<WSConfig, "onSignal" | "onStatus" | "onConnectionChange">) {
  const [status, setStatus] = useState<WSStatus>("disconnected");
  const [signals, setSignals] = useState<SignalData[]>([]);
  const [pipelineStatus, setPipelineStatus] = useState<Record<string, PipelineStatus>>({});
  const wsRef = useRef<TuyulWebSocket | null>(null);

  useEffect(() => {
    const ws = new TuyulWebSocket({
      ...config,
      onSignal: (signal) => {
        setSignals((prev) => [signal, ...prev].slice(0, 50)); // keep last 50
      },
      onStatus: (ps) => {
        setPipelineStatus((prev) => ({ ...prev, [ps.pair]: ps }));
      },
      onConnectionChange: setStatus,
    });

    ws.connect();
    wsRef.current = ws;

    return () => {
      ws.disconnect();
    };
  }, [config.url, config.token]);

  const reconnect = useCallback(() => {
    wsRef.current?.disconnect();
    wsRef.current?.connect();
  }, []);

  return { status, signals, pipelineStatus, reconnect };
}
*/
