"use client";

import { requestCancelPending } from "@/services/tradeService";
import { useProtectedMutation } from "./useProtectedMutation";

export function useCancelPendingMutation(accountId?: string, tradeId?: string) {
  return useProtectedMutation(
    {
      mutationKey: "cancel_pending",
      accountId,
      tradeId,
      invalidateQueryKeys: [["trades", accountId]],
      successTitle: "Cancel pending submitted",
      successDescription: "Cancel pending request acknowledged by backend.",
    },
    async () => requestCancelPending(tradeId ?? "")
  );
}
