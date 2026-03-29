"use client";

import { useEffect, useRef, useCallback } from "react";
import { useTradeDeskStore } from "@/store/useTradeDeskStore";
import { TradeDeskResponseSchema } from "../model/tradeDeskSchema";
import type { TradeDeskTrade } from "../model/tradeDeskSchema";
import { bearerHeader, fetchWsTicket } from "@/lib/auth";
import { getWsBaseUrl, getRestPrefix } from "@/lib/env";
import { createRafListBatcher } from "@/lib/realtime/rafBatcher";

/** Build a full WebSocket URL pointing at the Railway backend. */
function buildWsUrl(path: string, ticket: string): string {
  const base = getWsBaseUrl();
  const tokenQuery = ticket ? `?token=${encodeURIComponent(ticket)}` : "";
  return `${base}${path}${tokenQuery}`;
}

// ─── useLiveTrades ───────────────────────────────────────────
// Connects to /ws/trades and patches the TradeDeskStore on each event.

export function useLiveTrades(wsActiveRef?: React.MutableRefObject<boolean>) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const backoffRef = useRef(1000); // exponential backoff start 1s
  const patchTrade = useTradeDeskStore((s) => s.patchTrade);
  const removeTrade = useTradeDeskStore((s) => s.removeTrade);
  const setExecutionMismatch = useTradeDeskStore((s) => s.setExecutionMismatch);

  const connect = useCallback(async () => {
    if (typeof window === "undefined") return;

    const ticket = await fetchWsTicket() ?? "";
    const url = buildWsUrl("/ws/trades", ticket);

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
        // Mark WS as active on first message — prevents REST from overwriting
        if (wsActiveRef) wsActiveRef.current = true;
        backoffRef.current = 1000; // reset backoff on successful message

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
      // Allow REST polling to take over while WS is disconnected
      if (wsActiveRef) wsActiveRef.current = false;
      // Exponential backoff: 1s, 2s, 4s, 8s ... max 30s
      const delay = backoffRef.current;
      backoffRef.current = Math.min(delay * 2, 30_000);
      reconnectTimerRef.current = setTimeout(connect, delay);
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
  const backoffRef = useRef(1000);

  const connect = useCallback(async () => {
    if (typeof window === "undefined") return;

    const ticket = await fetchWsTicket() ?? "";
    const url = buildWsUrl("/ws/prices", ticket);

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onmessage = (ev) => {
      try {
        backoffRef.current = 1000; // reset backoff on message
        const msg = JSON.parse(ev.data);
        const payload = msg.payload ?? msg;
        if (payload.symbol && typeof payload.price === "number") {
          // Direct mutation on ref — avoids spread allocation on every tick
          pricesRef.current[payload.symbol as string] = payload.price as number;
        } else if (payload.prices && typeof payload.prices === "object") {
          Object.assign(pricesRef.current, payload.prices as Record<string, number>);
        }
      } catch {
        // Ignore
      }
    };

    ws.onclose = () => {
      wsRef.current = null;
      const delay = backoffRef.current;
      backoffRef.current = Math.min(delay * 2, 30_000);
      reconnectTimerRef.current = setTimeout(connect, delay);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, []);

  useEffect(() => {
    void connect();
    return () => {
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

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
        const res = await fetch(`${getRestPrefix()}/api/v1/trades/desk`, {
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

  // Start WS subscriptions — pass wsActiveRef so WS can flag REST as stale
  useLiveTrades(wsActiveRef);

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
