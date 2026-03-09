import { z } from "zod";
import { TradeListSchema } from "@/schema/tradeSchema";
import { apiClient } from "./apiClient";

const TradeActionResponseSchema = z.object({
  ok: z.boolean().optional(),
  message: z.string().optional(),
  trade_id: z.string().optional(),
});

export type TradeActionResponse = z.infer<typeof TradeActionResponseSchema>;

export async function fetchTrades(accountId?: string) {
  const response = await apiClient.get("/api/v1/trades", {
    params: {
      ...(accountId ? { account_id: accountId } : {}),
    },
  });

  return TradeListSchema.parse(response.data);
}

export async function submitTradeAction(tradeId: string, action: string) {
  const response = await apiClient.post(`/api/v1/trades/${tradeId}/action`, {
    action,
  });

  return TradeActionResponseSchema.parse(response.data);
}
