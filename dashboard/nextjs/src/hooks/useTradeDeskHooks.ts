"use client";

import { useEffect, useRef, useCallback } from "react";
import { useTradeDeskStore } from "@/store/useTradeDeskStore";
import { TradeDeskResponseSchema } from "@/schema/tradeDeskSchema";
import type { TradeDeskTrade } from "@/schema/tradeDeskSchema";
import { bearerHeader, getTransportToken } from "@/lib/auth";
import { createRafListBatcher } from "@/lib/realtime/rafBatcher";

// ─── useLiveTrades ───────────────────────────────────────────
// Connects to /ws/trades and patches the TradeDeskStore on each event.

export function useLiveTrades() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const patchTrade = useTradeDeskStore((s) => s.patchTrade);
  const removeTrade = useTradeDeskStore((s) => s.removeTrade);
  const setExecutionMismatch = useTradeDeskStore((s) => s.setExecutionMismatch);

  const connect = useCallback(() => {
    if (typeof window === "undefined") return;

    const token = getTransportToken() ?? "";
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const tokenQuery = token ? `?token=${encodeURIComponent(token)}` : "";
    const url = `${protocol}//${window.location.host}/ws/trades${tokenQuery}`;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    // RAF batcher: collapses burst trade_update events within the same frame
    // into a single patchTrade call per trade_id (last-write-wins).
    const patchBatcher = createRafListBatcher<TradeDeskTrade>({
      getKey: (t) => t.trade_id,
      onFlush: (trades) => {
        for (const trade of trades) {
          patchTrade(trade);
        }
      },
    });

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        const eventType = msg.event_type ?? msg.type;
        const payload = msg.payload ?? msg;

        if (eventType === "trade_update" || eventType === "TRADE_UPDATE") {
          const trade = payload as TradeDeskTrade;
          if (trade.trade_id) {
            // Queue into RAF batcher — flushes once per animation frame
            patchBatcher.push(trade);
          }
        } else if (eventType === "trade_removed" || eventType === "TRADE_REMOVED") {
          const tradeId = payload.trade_id;
          // Removals are low-frequency; apply directly without batching
          if (tradeId) removeTrade(tradeId);
        } else if (eventType === "execution_mismatch" || eventType === "EXECUTION_MISMATCH") {
          const tradeId = payload.trade_id;
          const flags = payload.flags ?? [payload.message ?? "SYNC_MISMATCH"];
          // Mismatch flags are low-frequency; apply directly without batching
          if (tradeId) setExecutionMismatch(tradeId, flags);
        }
      } catch {
        // Ignore parse errors (heartbeat pings etc.)
      }
    };

    ws.onclose = () => {
      patchBatcher.dispose();
      wsRef.current = null;
      reconnectTimerRef.current = setTimeout(connect, 3000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [patchTrade, removeTrade, setExecutionMismatch]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);
}

// ─── useTradeDeskLivePrices ──────────────────────────────────
// Connects to /ws/prices via connectLiveUpdates() and returns a ref map.

export function useTradeDeskLivePrices() {
  const pricesRef = useRef<Record<string, number>>({});
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    if (typeof window === "undefined") return;

    const token = getTransportToken() ?? "";
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const tokenQuery = token ? `?token=${encodeURIComponent(token)}` : "";
    const url = `${protocol}//${window.location.host}/ws/prices${tokenQuery}`;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        const payload = msg.payload ?? msg;
        if (payload.symbol && typeof payload.price === "number") {
          pricesRef.current = {
            ...pricesRef.current,
            [payload.symbol as string]: payload.price as number,
          };
        } else if (payload.prices && typeof payload.prices === "object") {
          pricesRef.current = { ...pricesRef.current, ...(payload.prices as Record<string, number>) };
        }
      } catch {
        // Ignore
      }
    };

    ws.onclose = () => {
      wsRef.current = null;
      reconnectTimerRef.current = setTimeout(connect, 3000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, []);

  return pricesRef;
}

// ─── useTradeDeskState ───────────────────────────────────────
// Composite hook: fetches initial desk snapshot + live WS updates.

export function useTradeDeskState() {
  const store = useTradeDeskStore();
  const applyDeskSnapshot = useTradeDeskStore((s) => s.applyDeskSnapshot);

  // Track whether WS has pushed data — prevents stale REST snapshot from overwriting
  const wsActiveRef = useRef(false);

  // Initial REST fetch
  useEffect(() => {
    let cancelled = false;

    async function fetchDesk() {
      try {
        const auth = bearerHeader();
        const res = await fetch("/api/v1/trades/desk", {
          credentials: "include",
          headers: {
            ...(auth ? { Authorization: auth } : {}),
          },
        });
        if (!res.ok) return;
        const json = await res.json();
        const parsed = TradeDeskResponseSchema.safeParse(json);
        if (!cancelled && parsed.success) {
          // Only apply REST snapshot if WS hasn't already delivered fresher data
          if (!wsActiveRef.current) {
            applyDeskSnapshot(parsed.data);
          }
        }
      } catch {
        // Silently fail initial fetch — WS will provide updates
      }
    }

    fetchDesk();

    // Re-fetch every 30s as a fallback (was 10s; reduced since WS is reliable now)
    const interval = setInterval(fetchDesk, 30_000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [applyDeskSnapshot]);

  // Start WS subscriptions (now using connectLiveUpdates with proper reconnect)
  useLiveTrades();

  return {
    activeTab: store.activeTab,
    setActiveTab: store.setActiveTab,
    pendingTrades: store.pendingTrades,
    openTrades: store.openTrades,
    closedTrades: store.closedTrades,
    cancelledTrades: store.cancelledTrades,
    selectedTradeId: store.selectedTradeId,
    setSelectedTradeId: store.setSelectedTradeId,
    exposure: store.exposure,
    anomalies: store.anomalies,
    counts: store.counts,
    executionMismatchFlags: store.executionMismatchFlags,
  };
}
