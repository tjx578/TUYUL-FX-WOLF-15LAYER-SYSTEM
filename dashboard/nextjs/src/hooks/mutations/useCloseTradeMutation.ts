"use client";

import { requestCloseTrade } from "@/services/tradeService";
import { useProtectedMutation } from "./useProtectedMutation";

export function useCloseTradeMutation(accountId?: string, tradeId?: string) {
  return useProtectedMutation(
    {
      mutationKey: "close_trade",
      accountId,
      tradeId,
      invalidateQueryKeys: [["trades", accountId]],
      successTitle: "Close trade submitted",
      successDescription: "Close trade request acknowledged by backend.",
    },
    async () => requestCloseTrade(tradeId ?? "")
  );
}
