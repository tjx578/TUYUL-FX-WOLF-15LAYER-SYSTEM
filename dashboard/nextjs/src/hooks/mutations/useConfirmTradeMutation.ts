"use client";

import { confirmTrade } from "@/lib/api";
import { useProtectedMutation } from "./useProtectedMutation";

export function useConfirmTradeMutation(accountId?: string, tradeId?: string) {
    return useProtectedMutation(
        {
            mutationKey: "confirm_trade",
            accountId,
            tradeId,
            invalidateQueryKeys: [["trades", accountId], ["trades"]],
            successTitle: "Trade confirmed",
            successDescription: "Trade confirmation sent to broker.",
        },
        async () => confirmTrade(tradeId ?? "")
    );
}
