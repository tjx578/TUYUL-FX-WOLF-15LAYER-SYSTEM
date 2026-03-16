"use client";

import { useEffect, useRef } from "react";
import { useTradeDeskStore } from "@/store/useTradeDeskStore";
import { TradeDeskResponseSchema } from "@/schema/tradeDeskSchema";
import type { TradeDeskTrade } from "@/schema/tradeDeskSchema";
import { bearerHeader } from "@/lib/auth";
import { connectLiveUpdates } from "@/lib/realtime/realtimeClient";
import type { WsEventParsed } from "@/schema/wsEventSchema";

// ─── useLiveTrades ───────────────────────────────────────────
// Connects to /ws/trades and patches the TradeDeskStore on each event.

export function useLiveTrades() {
  const patchTrade = useTradeDeskStore((s) => s.patchTrade);
  const removeTrade = useTradeDeskStore((s) => s.removeTrade);
  const setExecutionMismatch = useTradeDeskStore((s) => s.setExecutionMismatch);

  useEffect(() => {
    const controls = connectLiveUpdates({
      path: "/ws/trades",
      onEvent: (event) => {
        const eventType = (event as Record<string, unknown>).type as string;
        const payload = (event as Record<string, unknown>).payload as Record<string, unknown>;

        if (eventType === "trade_update" || eventType === "TRADE_UPDATE" || eventType === "TradeUpdate") {
          const trade = payload as unknown as TradeDeskTrade;
          if (trade.trade_id) patchTrade(trade);
        } else if (eventType === "trade_removed" || eventType === "TRADE_REMOVED") {
          const tradeId = payload.trade_id as string;
          if (tradeId) removeTrade(tradeId);
        } else if (eventType === "execution_mismatch" || eventType === "EXECUTION_MISMATCH") {
          const tradeId = payload.trade_id as string;
          const flags = (payload.flags as string[]) ?? [(payload.message as string) ?? "SYNC_MISMATCH"];
          if (tradeId) setExecutionMismatch(tradeId, flags);
        }
      },
      onError: (err) => {
        if (process.env.NODE_ENV !== "production") {
          console.warn("[useLiveTrades] WS error:", err);
        }
      },
    });

    return () => controls.close();
  }, [patchTrade, removeTrade, setExecutionMismatch]);
}

// ─── useLivePrices ───────────────────────────────────────────
// Connects to /ws/prices and returns a ref map of current prices.

export function useLivePrices() {
  const pricesRef = useRef<Record<string, number>>({});

  useEffect(() => {
    const controls = connectLiveUpdates({
      path: "/ws/prices",
      onEvent: (event: WsEventParsed) => {
        const payload = (event as Record<string, unknown>).payload as Record<string, unknown>;
        if (payload.symbol && typeof payload.price === "number") {
          pricesRef.current = {
            ...pricesRef.current,
            [payload.symbol as string]: payload.price as number,
          };
        } else if (payload.prices && typeof payload.prices === "object") {
          pricesRef.current = { ...pricesRef.current, ...(payload.prices as Record<string, number>) };
        }
      },
      onError: (err) => {
        if (process.env.NODE_ENV !== "production") {
          console.warn("[useLivePrices] WS error:", err);
        }
      },
    });

    return () => controls.close();
  }, []);

  return pricesRef;
}

// ─── useTradeDeskState ───────────────────────────────────────
// Composite hook: fetches initial desk snapshot + live WS updates.

export function useTradeDeskState() {
  const store = useTradeDeskStore();
  const applyDeskSnapshot = useTradeDeskStore((s) => s.applyDeskSnapshot);

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
          applyDeskSnapshot(parsed.data);
        }
      } catch {
        // Silently fail initial fetch — WS will provide updates
      }
    }

    fetchDesk();

    // Re-fetch every 10s as a fallback
    const interval = setInterval(fetchDesk, 10_000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [applyDeskSnapshot]);

  // Start WS subscriptions
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
