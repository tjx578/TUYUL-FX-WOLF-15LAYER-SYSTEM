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

// Domain-specific WS endpoint events (prices, risk)
export const PriceUpdatedEventSchema = z.object({
  type: z.literal("PriceUpdated"),
  payload: z.record(z.string(), z.unknown()),
});

export const PricesSnapshotEventSchema = z.object({
  type: z.literal("PricesSnapshot"),
  payload: z.record(z.string(), z.unknown()),
});

export const RiskUpdatedEventSchema = z.object({
  type: z.literal("RiskUpdated"),
  payload: z.record(z.string(), z.unknown()),
});

// Additional event types forwarded from backend that are not in the core schema
export const VerdictUpdatedEventSchema = z.object({
  type: z.literal("VerdictUpdated"),
  payload: z.record(z.string(), z.unknown()),
});

export const TradeUpdateEventSchema = z.object({
  type: z.literal("TradeUpdate"),
  payload: z.record(z.string(), z.unknown()),
});

export const AlertBroadcastEventSchema = z.object({
  type: z.literal("AlertBroadcast"),
  payload: z.record(z.string(), z.unknown()),
});

export const SignalGeneratedEventSchema = z.object({
  type: z.literal("SignalGenerated"),
  payload: z.record(z.string(), z.unknown()),
});

export const WsEventSchema = z.discriminatedUnion("type", [
  PipelineResultUpdatedEventSchema,
  ExecutionStateUpdatedEventSchema,
  RiskStateUpdatedEventSchema,
  SystemStatusUpdatedEventSchema,
  PreferencesUpdatedEventSchema,
  PriceUpdatedEventSchema,
  PricesSnapshotEventSchema,
  RiskUpdatedEventSchema,
  VerdictUpdatedEventSchema,
  TradeUpdateEventSchema,
  AlertBroadcastEventSchema,
  SignalGeneratedEventSchema,
]);

export type WsEvent = z.infer<typeof WsEventSchema>;
export type WsEventParsed = z.infer<typeof WsEventSchema>;
