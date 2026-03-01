import { useEffect, useCallback, useRef, useState } from "react";
import { API_BASE_URL } from "./env";

/* ------------------------------------------------------------------ */
/*  Generic fetch helper                                               */
/* ------------------------------------------------------------------ */

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body}`);
  }

  return res.json() as Promise<T>;
}

/* ------------------------------------------------------------------ */
/*  Verdict types (mirrors L12 schema – read-only on dashboard side)   */
/* ------------------------------------------------------------------ */

export interface L12Verdict {
  symbol: string;
  verdict: "EXECUTE" | "HOLD" | "NO_TRADE" | "ABORT";
  confidence: number;
  direction?: string;
  entry_price?: number;
  stop_loss?: number;
  take_profit_1?: number;
  rr?: number;
  scores?: Record<string, number>;
  signal_id?: string;
  timestamp?: string;
}

/* ------------------------------------------------------------------ */
/*  REST: fetch all verdicts                                           */
/* ------------------------------------------------------------------ */

/**
 * Fetch the full list of current L12 verdicts.
 * Endpoint: GET /api/v1/verdict/all
 *
 * Dashboard may display these but MUST NOT override or mutate them.
 */
export async function fetchVerdicts(): Promise<L12Verdict[]> {
  return apiFetch<L12Verdict[]>("/api/v1/verdict/all");
}

/**
 * Fetch a single verdict by symbol.
 * Endpoint: GET /api/v1/verdict/:symbol
 */
export async function fetchVerdictBySymbol(
  symbol: string,
): Promise<L12Verdict> {
  return apiFetch<L12Verdict>(`/api/v1/verdict/${encodeURIComponent(symbol)}`);
}

/* ------------------------------------------------------------------ */
/*  SSE: live verdict stream hook                                      */
/* ------------------------------------------------------------------ */

export interface UseVerdictStreamOptions {
  /** Auto-reconnect on error (default true) */
  reconnect?: boolean;
  /** Reconnect delay in ms (default 3 000) */
  reconnectDelay?: number;
  /** Maximum reconnect delay cap in ms (default 30 000) */
  maxReconnectDelay?: number;
}

/**
 * React hook that subscribes to the server-sent-event stream of L12
 * verdicts and keeps local state in sync.
 *
 * The dashboard consumes verdicts **read-only**; it never sends
 * decisions back through this channel (constitutional boundary).
 */
export function useVerdictStream(opts?: UseVerdictStreamOptions) {
  const {
    reconnect = true,
    reconnectDelay = 3_000,
    maxReconnectDelay = 30_000,
  } = opts ?? {};

  const [verdicts, setVerdicts] = useState<L12Verdict[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryCount = useRef(0);

  const connect = useCallback(() => {
    // Clean up any previous connection
    esRef.current?.close();
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current);
      reconnectTimer.current = null;
    }

    const url = `${API_BASE_URL}/stream/verdicts`;
    const es = new EventSource(url);
    esRef.current = es;

    es.onopen = () => {
      setConnected(true);
      setError(null);
      retryCount.current = 0; // reset backoff on successful connect
    };

    es.onmessage = (event: MessageEvent) => {
      try {
        const data: L12Verdict | L12Verdict[] = JSON.parse(event.data);

        if (Array.isArray(data)) {
          // Full snapshot push – replace state
          setVerdicts(data);
        } else {
          // Single verdict update – upsert by symbol
          setVerdicts((prev) => {
            const idx = prev.findIndex((v) => v.symbol === data.symbol);
            if (idx === -1) return [...prev, data];
            const next = [...prev];
            next[idx] = data;
            return next;
          });
        }
      } catch (err) {
        console.error("[useVerdictStream] Failed to parse event:", err);
      }
    };

    es.onerror = () => {
      setConnected(false);
      setError("Verdict stream disconnected");
      es.close();

      if (reconnect) {
        // Exponential backoff: delay * 2^retryCount, capped at maxReconnectDelay
        const delay = Math.min(
          reconnectDelay * 2 ** retryCount.current,
          maxReconnectDelay,
        );
        retryCount.current += 1;
        console.warn(
          `[useVerdictStream] Reconnecting in ${delay}ms (attempt ${retryCount.current})`,
        );
        reconnectTimer.current = setTimeout(connect, delay);
      }
    };
  }, [reconnect, reconnectDelay, maxReconnectDelay]);

  useEffect(() => {
    connect();

    return () => {
      esRef.current?.close();
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };
  }, [connect]);

  return { verdicts, connected, error } as const;
}

