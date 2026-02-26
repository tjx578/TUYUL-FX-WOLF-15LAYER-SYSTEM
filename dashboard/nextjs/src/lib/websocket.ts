// ============================================================
// TUYUL FX Wolf-15 — WebSocket Hooks
// Channels: /ws/prices, /ws/trades, /ws/candles, /ws/risk, /ws/equity
// ============================================================

"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import type {
  PriceData,
  Trade,
  CandleData,
  RiskSnapshot,
  DrawdownData,
  AlertEvent,
} from "@/types";

const WS_URL =
  (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(
    /^http/,
    "ws"
  );

const RECONNECT_DELAY_MS = 3000;
const MAX_RECONNECT_ATTEMPTS = 10;

// ─── BASE WS HOOK ─────────────────────────────────────────────

interface UseWolfWebSocketOptions {
  enabled?: boolean;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (e: Event) => void;
}

export function useWolfWebSocket<T>(
  path: string,
  options: UseWolfWebSocketOptions = {}
) {
  const { enabled = true, onOpen, onClose, onError } = options;
  const [data, setData] = useState<T | null>(null);
  const [connected, setConnected] = useState(false);
  const [reconnectCount, setReconnectCount] = useState(0);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const connect = useCallback(() => {
    if (!mountedRef.current || !enabled) return;
    if (reconnectCount >= MAX_RECONNECT_ATTEMPTS) return;

    const token =
      typeof window !== "undefined"
        ? localStorage.getItem("wolf15_token")
        : null;
    const url = token
      ? `${WS_URL}${path}?token=${token}`
      : `${WS_URL}${path}`;

    try {
      const ws = new WebSocket(url);

      ws.onopen = () => {
        if (!mountedRef.current) return;
        setConnected(true);
        setReconnectCount(0);
        onOpen?.();
      };

      ws.onclose = () => {
        if (!mountedRef.current) return;
        setConnected(false);
        onClose?.();

        reconnectTimerRef.current = setTimeout(() => {
          if (mountedRef.current) {
            setReconnectCount((c) => c + 1);
            connect();
          }
        }, RECONNECT_DELAY_MS);
      };

      ws.onerror = (e) => {
        onError?.(e);
      };

      ws.onmessage = (event) => {
        if (!mountedRef.current) return;
        try {
          setData(JSON.parse(event.data as string) as T);
        } catch {
          // ignore malformed frames
        }
      };

      wsRef.current = ws;
    } catch {
      // ignore connection errors; reconnect will handle it
    }
  }, [path, enabled, reconnectCount, onOpen, onClose, onError]);

  useEffect(() => {
    mountedRef.current = true;
    if (enabled) connect();
    return () => {
      mountedRef.current = false;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      wsRef.current?.close();
    };
  }, [connect, enabled]);

  const send = useCallback((payload: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(payload));
    }
  }, []);

  return { data, connected, send, reconnectCount };
}

// ─── TYPED CHANNEL HOOKS ─────────────────────────────────────

/** Real-time bid/ask per pair */
export function usePricesWS(enabled = true) {
  return useWolfWebSocket<Record<string, PriceData>>("/ws/prices", {
    enabled,
  });
}

/** Real-time trade state changes */
export function useTradesWS(enabled = true) {
  return useWolfWebSocket<Trade>("/ws/trades", { enabled });
}

/** OHLC candles M1/M5/M15/H1 */
export function useCandlesWS(pair?: string, timeframe = "M15", enabled = true) {
  const path = pair
    ? `/ws/candles?pair=${pair}&tf=${timeframe}`
    : `/ws/candles`;
  return useWolfWebSocket<CandleData>(path, { enabled });
}

/** Real-time drawdown updates */
export function useRiskWS(accountId?: string, enabled = true) {
  const path = accountId ? `/ws/risk?account_id=${accountId}` : `/ws/risk`;
  return useWolfWebSocket<RiskSnapshot>(path, { enabled });
}

/** Real-time equity curve points */
export function useEquityWS(accountId?: string, enabled = true) {
  const path = accountId
    ? `/ws/equity?account_id=${accountId}`
    : `/ws/equity`;
  return useWolfWebSocket<DrawdownData>(path, { enabled });
}

/** System alerts feed */
export function useAlertsWS(enabled = true) {
  const { data, connected } = useWolfWebSocket<AlertEvent>("/ws/alerts", {
    enabled,
  });
  const [alerts, setAlerts] = useState<AlertEvent[]>([]);

  useEffect(() => {
    if (data) {
      setAlerts((prev) => [data, ...prev].slice(0, 50));
    }
  }, [data]);

  return { alerts, connected };
}

// ─── MULTI-PRICE ACCUMULATOR ─────────────────────────────────

/** Accumulates a map of symbol → latest price from WS stream */
export function usePriceMap(enabled = true) {
  const { data, connected } = usePricesWS(enabled);
  const [priceMap, setPriceMap] = useState<Record<string, PriceData>>({});

  useEffect(() => {
    if (data) {
      setPriceMap((prev) => ({ ...prev, ...data }));
    }
  }, [data]);

  return { priceMap, connected };
}

// ─── EQUITY HISTORY ACCUMULATOR ──────────────────────────────

/** Accumulates equity points for charting */
export function useEquityHistory(accountId?: string, maxPoints = 200) {
  const { data, connected } = useEquityWS(accountId);
  const [history, setHistory] = useState<DrawdownData[]>([]);

  useEffect(() => {
    if (data) {
      setHistory((prev) => [...prev, data].slice(-maxPoints));
    }
  }, [data, maxPoints]);

  return { history, connected };
}
