import { z } from "zod";

export const PipelineResultSchema = z.object({
  symbol: z.string().min(1),
  account_id: z.string().min(1),
  verdict: z.enum(["EXECUTE_BUY", "EXECUTE_SELL", "HOLD", "NO_TRADE"]),
  confidence: z.number(),
  gate_state: z.enum(["PASS", "FAIL", "SKIP"]).optional(),
  governance_state: z
    .enum(["OK", "CAUTION", "DOWNGRADED", "BLOCKED"])
    .optional(),
}).passthrough();

export type PipelineResult = z.infer<typeof PipelineResultSchema>;
