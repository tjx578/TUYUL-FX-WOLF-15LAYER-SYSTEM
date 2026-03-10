import { z } from "zod";

export const ExecutionTradeSchema = z.object({
  trade_id: z.string().min(1),
  account_id: z.string().min(1),
  symbol: z.string().min(1),
  side: z.enum(["BUY", "SELL"]),
  lot: z.number(),
});

export const ExecutionStateUpdatedSchema = z.object({
  execution_state: z.string().min(1),
  trade: ExecutionTradeSchema,
});

export type ExecutionTrade = z.infer<typeof ExecutionTradeSchema>;
export type ExecutionStateUpdated = z.infer<typeof ExecutionStateUpdatedSchema>;
