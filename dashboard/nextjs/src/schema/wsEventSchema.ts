import { z } from "zod";
import { ExecutionStateUpdatedSchema } from "./executionSchema";
import { PipelineResultSchema } from "./pipelineResultSchema";
import { PreferencesSchema } from "./preferencesSchema";

const RiskStateSchema = z.object({
  account_id: z.string().min(1),
  dd_pct: z.number(),
});

const SystemStatusSchema = z.object({
  mode: z.union([z.literal("NORMAL"), z.literal("DEGRADED")]),
  reason: z.string().optional(),
  updated_at: z.string().optional(),
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

export const SystemStatusUpdatedEventSchema = z.object({
  type: z.literal("SystemStatusUpdated"),
  payload: SystemStatusSchema,
});

export const PreferencesUpdatedEventSchema = z.object({
  type: z.literal("PreferencesUpdated"),
  payload: PreferencesSchema,
});

export const WsEventSchema = z.discriminatedUnion("type", [
  PipelineResultUpdatedEventSchema,
  ExecutionStateUpdatedEventSchema,
  RiskStateUpdatedEventSchema,
  SystemStatusUpdatedEventSchema,
  PreferencesUpdatedEventSchema,
]);

export type WsEvent = z.infer<typeof WsEventSchema>;
export type WsEventParsed = z.infer<typeof WsEventSchema>;
