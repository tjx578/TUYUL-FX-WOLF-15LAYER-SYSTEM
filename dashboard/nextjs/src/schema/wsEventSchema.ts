import { z } from "zod";
import { ExecutionStateUpdatedSchema } from "./executionSchema";
import { PipelineResultSchema } from "./pipelineResultSchema";

const RiskStateSchema = z.object({
  account_id: z.string().min(1),
  dd_pct: z.number(),
});

export const PipelineResultUpdatedEventSchema = z.object({
  type: z.literal("PipelineResultUpdated"),
  payload: PipelineResultSchema,
});

export const ExecutionStateUpdatedEventSchema = z.object({
  type: z.literal("ExecutionStateUpdated"),
  payload: ExecutionStateUpdatedSchema,
});

export const RiskStateUpdatedEventSchema = z.object({
  type: z.literal("RiskStateUpdated"),
  payload: RiskStateSchema,
});

export const WsEventSchema = z.discriminatedUnion("type", [
  PipelineResultUpdatedEventSchema,
  ExecutionStateUpdatedEventSchema,
  RiskStateUpdatedEventSchema,
]);

export type WsEvent = z.infer<typeof WsEventSchema>;
export type WsEventParsed = z.infer<typeof WsEventSchema>;
