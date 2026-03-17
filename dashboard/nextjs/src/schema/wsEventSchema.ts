import { z } from "zod";
import { ExecutionStateUpdatedSchema } from "./executionSchema";
import {
  PipelineResultSchema,
  VerdictUpdatedPayloadSchema,
  VerdictSnapshotPayloadSchema,
  PipelineUpdatedPayloadSchema,
} from "./pipelineResultSchema";
import { PreferencesSchema } from "./preferencesSchema";

const RiskStateSchema = z.object({
  account_id: z.string().min(1),
  dd_pct: z.number(),
});

const SystemStatusSchema = z.object({
  mode: z.union([z.literal("NORMAL"), z.literal("SSE"), z.literal("POLLING"), z.literal("DEGRADED")]),
  reason: z.string().optional(),
  updated_at: z.string().optional(),
});

// ── Legacy / frontend-native event types ──

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

// ── Backend-native event types (normalised by realtimeClient) ──

export const VerdictUpdatedEventSchema = z.object({
  type: z.literal("VerdictUpdated"),
  payload: VerdictUpdatedPayloadSchema,
});

export const VerdictSnapshotEventSchema = z.object({
  type: z.literal("VerdictSnapshot"),
  payload: VerdictSnapshotPayloadSchema,
});

export const PipelineUpdatedEventSchema = z.object({
  type: z.literal("PipelineUpdated"),
  payload: PipelineUpdatedPayloadSchema,
});

export const WsEventSchema = z.discriminatedUnion("type", [
  // Legacy / frontend-native
  PipelineResultUpdatedEventSchema,
  ExecutionStateUpdatedEventSchema,
  RiskStateUpdatedEventSchema,
  SystemStatusUpdatedEventSchema,
  PreferencesUpdatedEventSchema,
  PriceUpdatedEventSchema,
  PricesSnapshotEventSchema,
  RiskUpdatedEventSchema,
  // Backend-native (normalised by realtimeClient)
  VerdictUpdatedEventSchema,
  VerdictSnapshotEventSchema,
  PipelineUpdatedEventSchema,
]);

export type WsEvent = z.infer<typeof WsEventSchema>;
export type WsEventParsed = z.infer<typeof WsEventSchema>;
