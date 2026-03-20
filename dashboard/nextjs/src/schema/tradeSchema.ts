import { z } from "zod";

export const TradeSchema = z.object({
  trade_id: z.string().min(1),
  account_id: z.string().min(1),
  symbol: z.string().min(1),
  side: z.enum(["BUY", "SELL"]),
  lot: z.number(),
  status: z.string().min(1).optional(),
  // Additional fields used by the UI (optional since not always present)
  pair: z.string().optional(),
  direction: z.string().optional(),
  lot_size: z.number().optional(),
  entry_price: z.number().optional(),
  stop_loss: z.number().optional(),
  take_profit: z.number().optional(),
  pnl: z.number().optional(),
  opened_at: z.string().optional(),
});

export const TradeListSchema = z.array(TradeSchema);

export type TradeParsed = z.infer<typeof TradeSchema>;
