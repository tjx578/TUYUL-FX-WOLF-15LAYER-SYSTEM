// ============================================================
// TUYUL FX Wolf-15 — WebSocket Hooks (legacy typed channel layer)
//
// These hooks are preserved for backwards compatibility with existing pages.
// New features should use the domain hooks from @/lib/realtime:
//   useLivePrices, useLiveTrades, useLiveRisk, useLiveSignals
//
// All hooks now delegate to realtimeClient — they inherit:
//   - exponential backoff with jitter
//   - infinite retry
//   - stale detection
//   - visibility-aware pause
//   - proper connection status machine
//
// Channels: /ws/prices, /ws/trades, /ws/candles, /ws/risk, /ws/equity, /ws/alerts
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
import { connectLiveUpdates } from "@/lib/realtime/realtimeClient";
import type { WsConnectionStatus } from "@/lib/realtime/connectionState";

// ─── BASE WS HOOK ─────────────────────────────────────────────

interface UseWolfWebSocketOptions {
  enabled?: boolean;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (e: unknown) => void;
}

export function useWolfWebSocket<T>(
  path: string,
  options: UseWolfWebSocketOptions = {}
) {
  const { enabled = true, onOpen, onClose, onError } = options;
  const [data, setData] = useState<T | null>(null);
  const [status, setStatus] = useState<WsConnectionStatus>("CONNECTING");
  const [reconnectCount, setReconnectCount] = useState(0);
  const controlsRef = useRef<ReturnType<typeof connectLiveUpdates> | null>(null);

  const connected = status === "LIVE";

  const connect = useCallback(() => {
    if (!enabled) return;

    const controls = connectLiveUpdates({
      path,
      onEvent: (event) => {
        // For typed channel hooks the payload IS the data — take first matching field
        const payload =
          (event as { payload?: T }).payload ??
          (event as unknown as T);
        setData(payload);
      },
      onStatusChange: (s) => {
        setStatus(s);
        if (s === "LIVE") {
          setReconnectCount(0);
          onOpen?.();
        }
        if (s === "DISCONNECTED") {
          onClose?.();
          setReconnectCount((c) => c + 1);
        }
      },
      onError: (e) => {
        onError?.(e);
      },
    });

    controlsRef.current = controls;
  }, [path, enabled, onOpen, onClose, onError]);

  useEffect(() => {
    connect();
    return () => {
      controlsRef.current?.close();
    };
  }, [connect]);

  const send = useCallback((payload: unknown) => {
    controlsRef.current?.send(payload);
  }, []);

  return { data, connected, status, send, reconnectCount };
}

// ─── TYPED CHANNEL HOOKS ─────────────────────────────────────

export function usePricesWS(enabled = true) {
  return useWolfWebSocket<Record<string, PriceData>>("/ws/prices", { enabled });
}

export function useTradesWS(enabled = true) {
  return useWolfWebSocket<Trade>("/ws/trades", { enabled });
}

export function useCandlesWS(pair?: string, timeframe = "M15", enabled = true) {
  const path = pair
    ? `/ws/candles?pair=${pair}&tf=${timeframe}`
    : `/ws/candles`;
  return useWolfWebSocket<CandleData>(path, { enabled });
}

export function useRiskWS(accountId?: string, enabled = true) {
  const path = accountId ? `/ws/risk?account_id=${accountId}` : `/ws/risk`;
  return useWolfWebSocket<RiskSnapshot>(path, { enabled });
}

export function useEquityWS(accountId?: string, enabled = true) {
  const path = accountId
    ? `/ws/equity?account_id=${accountId}`
    : `/ws/equity`;
  return useWolfWebSocket<DrawdownData>(path, { enabled });
}

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

// ─── ACCUMULATORS ─────────────────────────────────────────────

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
