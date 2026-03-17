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

// ── Domain event types (mapped from backend by realtimeClient) ──

export const SignalUpdatedEventSchema = z.object({
  type: z.literal("SignalUpdated"),
  payload: z.record(z.string(), z.unknown()),
});

export const TradeSnapshotEventSchema = z.object({
  type: z.literal("TradeSnapshot"),
  payload: z.record(z.string(), z.unknown()),
});

export const TradeUpdatedEventSchema = z.object({
  type: z.literal("TradeUpdated"),
  payload: z.record(z.string(), z.unknown()),
});

export const CandleSnapshotEventSchema = z.object({
  type: z.literal("CandleSnapshot"),
  payload: z.record(z.string(), z.unknown()),
});

export const CandleFormingEventSchema = z.object({
  type: z.literal("CandleForming"),
  payload: z.record(z.string(), z.unknown()),
});

export const EquityUpdatedEventSchema = z.object({
  type: z.literal("EquityUpdated"),
  payload: z.record(z.string(), z.unknown()),
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
  // Domain events (mapped from backend)
  SignalUpdatedEventSchema,
  TradeSnapshotEventSchema,
  TradeUpdatedEventSchema,
  CandleSnapshotEventSchema,
  CandleFormingEventSchema,
  EquityUpdatedEventSchema,
]);

export type WsEvent = z.infer<typeof WsEventSchema>;
export type WsEventParsed = z.infer<typeof WsEventSchema>;
