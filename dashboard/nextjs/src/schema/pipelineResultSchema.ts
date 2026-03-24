import { z } from "zod";

export const PipelineResultSchema = z.object({
  symbol: z.string().min(1),
  account_id: z.string().optional(),
  // verdict can be undefined/null when engine hasn't run yet — default to "HOLD"
  verdict: z
    .enum(["EXECUTE", "EXECUTE_BUY", "EXECUTE_SELL", "EXECUTE_REDUCED_RISK", "HOLD", "NO_TRADE", "ABORT"])
    .optional()
    .nullable()
    .default("HOLD")
    .transform((v) => v ?? "HOLD"),
  confidence: z.number().optional().default(0),
  gate_state: z.enum(["PASS", "FAIL", "SKIP"]).optional(),
  governance_state: z
    .enum(["OK", "CAUTION", "DOWNGRADED", "BLOCKED"])
    .optional(),
});

export type PipelineResult = z.infer<typeof PipelineResultSchema>;

/**
 * Schema for the raw verdict payload sent by the backend on /ws/verdict.
 * verdict.update → { pair, verdict: { ...raw L12 verdict data } }
 */
export const VerdictUpdatedPayloadSchema = z
  .object({
    pair: z.string().min(1),
    verdict: z.record(z.string(), z.unknown()),
  })
  .passthrough();

export type VerdictUpdatedPayload = z.infer<typeof VerdictUpdatedPayloadSchema>;

/**
 * Schema for verdict.snapshot → { pair, verdicts: Record<symbol, verdict> }
 */
export const VerdictSnapshotPayloadSchema = z
  .object({
    pair: z.string().nullable().optional(),
    verdicts: z.record(z.string(), z.unknown()),
  })
  .passthrough();

export type VerdictSnapshotPayload = z.infer<typeof VerdictSnapshotPayloadSchema>;

/**
 * Schema for pipeline.update → { pair, pipeline: { ...UI-shaped data } }
 */
export const PipelineUpdatedPayloadSchema = z
  .object({
    pair: z.string().min(1),
    pipeline: z.record(z.string(), z.unknown()),
  })
  .passthrough();

export type PipelineUpdatedPayload = z.infer<typeof PipelineUpdatedPayloadSchema>;
