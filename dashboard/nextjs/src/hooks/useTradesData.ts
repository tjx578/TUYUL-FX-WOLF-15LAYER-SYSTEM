"use client";

import { tradesMock } from "@/lib/mock/trades";

export function useTradesData() {
  function closeTrade(id: string) {
    // TODO: replace with POST /close-trade via adapter
    alert(`Close trade ${id} -> replace with POST /close-trade`);
  }

  return { cards: tradesMock.cards, items: tradesMock.items, closeTrade };
}
