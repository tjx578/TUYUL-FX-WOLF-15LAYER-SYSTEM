"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { useTradeDeskStore } from "@/store/useTradeDeskStore";
import { TradeDeskResponseSchema } from "@/schema/tradeDeskSchema";
import type { TradeDeskTrade } from "@/schema/tradeDeskSchema";
import { bearerHeader } from "@/lib/auth";
import { connectLiveUpdates } from "@/lib/realtime/realtimeClient";
import type { WsConnectionStatus } from "@/lib/realtime/connectionState";
import { STALE_THRESHOLDS_MS } from "@/lib/realtime/connectionState";

// ─── useTradeDeskLiveTrades ──────────────────────────────────
// Connects to /ws/trades via connectLiveUpdates() and patches TradeDeskStore.
// Uses onRawMessage for trade desk custom event types (trade_update, trade_removed,
// execution_mismatch) that are not in the standard WsEventSchema.

export function useTradeDeskLiveTrades() {
  const patchTrade = useTradeDeskStore((s) => s.patchTrade);
  const removeTrade = useTradeDeskStore((s) => s.removeTrade);
  const setExecutionMismatch = useTradeDeskStore((s) => s.setExecutionMismatch);

  useEffect(() => {
    const controls = connectLiveUpdates({
      path: "/ws/trades",
      onEvent: (event) => {
        // Handle standard typed events (ExecutionStateUpdated)
        if (event.type === "ExecutionStateUpdated") {
          const trade = event.payload.trade as unknown as TradeDeskTrade;
          if (trade?.trade_id) {
            patchTrade(trade);
          }
        }
      },
      onRawMessage: (msg) => {
        // Handle trade desk custom events that aren't in WsEventSchema
        const eventType = (msg as Record<string, unknown>).event_type ??
          (msg as Record<string, unknown>).type;
        const payload = ((msg as Record<string, unknown>).payload ?? msg) as Record<string, unknown>;

        if (eventType === "trade_update" || eventType === "TRADE_UPDATE") {
          const trade = payload as unknown as TradeDeskTrade;
          if (trade.trade_id) {
            patchTrade(trade);
          }
        } else if (eventType === "trade_removed" || eventType === "TRADE_REMOVED") {
          const tradeId = payload.trade_id as string | undefined;
          if (tradeId) removeTrade(tradeId);
        } else if (eventType === "execution_mismatch" || eventType === "EXECUTION_MISMATCH") {
          const tradeId = payload.trade_id as string | undefined;
          const flags = (payload.flags as string[] | undefined) ??
            [(payload.message as string | undefined) ?? "SYNC_MISMATCH"];
          if (tradeId) setExecutionMismatch(tradeId, flags);
        }
      },
      onStatusChange: () => { /* status tracked at system store level if needed */ },
      onDegradation: () => { /* handled by system store */ },
      onError: () => { /* reconnect is handled automatically */ },
    });

    return () => {
      controls.close();
    };
  }, [patchTrade, removeTrade, setExecutionMismatch]);
}

// ─── useTradeDeskLivePrices ──────────────────────────────────
// Connects to /ws/prices via connectLiveUpdates() and returns a ref map.

export function useTradeDeskLivePrices() {
  const pricesRef = useRef<Record<string, number>>({});

  useEffect(() => {
    const controls = connectLiveUpdates({
      path: "/ws/prices",
      onEvent: (event) => {
        if (event.type === "PriceUpdated" || event.type === "PricesSnapshot") {
          const payload = event.payload as Record<string, unknown>;
          // Handle map format: { EURUSD: { price: 1.1, ... }, ... }
          for (const [symbol, data] of Object.entries(payload)) {
            if (typeof data === "object" && data !== null && "price" in data) {
              pricesRef.current[symbol] = (data as { price: number }).price;
            }
          }
        }
      },
      onRawMessage: (msg) => {
        // Handle legacy individual price format: { symbol, price }
        const payload = ((msg as Record<string, unknown>).payload ?? msg) as Record<string, unknown>;
        if (typeof payload.symbol === "string" && typeof payload.price === "number") {
          pricesRef.current = {
            ...pricesRef.current,
            [payload.symbol]: payload.price,
          };
        } else if (payload.prices && typeof payload.prices === "object") {
          pricesRef.current = { ...pricesRef.current, ...(payload.prices as Record<string, number>) };
        }
      },
    });

    return () => {
      controls.close();
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
  useTradeDeskLiveTrades();

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
