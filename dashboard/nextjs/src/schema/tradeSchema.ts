import { z } from "zod";

export const TradeSchema = z.object({
  trade_id: z.string().min(1),
  account_id: z.string().min(1),
  symbol: z.string().min(1),
  side: z.enum(["BUY", "SELL"]),
  lot: z.number(),
  status: z.string().min(1).optional(),
});

export const TradeListSchema = z.array(TradeSchema);

export type TradeParsed = z.infer<typeof TradeSchema>;
