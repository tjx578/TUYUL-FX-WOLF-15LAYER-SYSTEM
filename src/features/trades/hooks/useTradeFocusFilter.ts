"use client";

import { useMemo } from "react";

interface FocusFilterInput {
  accountId: string | null;
  signalId: string | null;
}

interface TradeShape {
  trade_id: string;
  account_id?: string;
  signal_id?: string;
}

export function useTradeFocusFilter<T extends TradeShape>(
  trades: T[],
  focus: FocusFilterInput,
) {
  return useMemo(() => {
    if (!focus.accountId && !focus.signalId) return trades;

    return trades.filter((trade) => {
      const accountOk = focus.accountId ? trade.account_id === focus.accountId : true;
      const signalOk = focus.signalId ? trade.signal_id === focus.signalId : true;
      return accountOk && signalOk;
    });
  }, [trades, focus.accountId, focus.signalId]);
}
