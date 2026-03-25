import type { ExecutionStateUpdatedPayload } from "./execution";
import type { PipelineResultView } from "./pipelineResult";
import type { OperatorPreferences } from "./preferences";

export interface RiskStateView {
  account_id: string;
  dd_pct: number;
}

export interface SystemStatusView {
  mode: "NORMAL" | "SSE" | "POLLING" | "DEGRADED" | "RECONNECTING_WS" | "POLLING_REST" | "STALE" | "STALE_PRESERVED" | "NO_PRODUCER" | "NO_TRANSPORT" | "DEGRADED_BUT_REFRESHING";
  reason?: string;
  updated_at?: string;
}

export interface PipelineResultUpdatedEvent {
  type: "PipelineResultUpdated";
  payload: PipelineResultView;
}

export interface ExecutionStateUpdatedEvent {
  type: "ExecutionStateUpdated";
  payload: ExecutionStateUpdatedPayload;
}

export interface RiskStateUpdatedEvent {
  type: "RiskStateUpdated";
  payload: RiskStateView;
}

export interface SystemStatusUpdatedEvent {
  type: "SystemStatusUpdated";
  payload: SystemStatusView;
}

export interface PreferencesUpdatedEvent {
  type: "PreferencesUpdated";
  payload: OperatorPreferences;
}

// ── Backend-native event types (normalised by realtimeClient) ──

export interface VerdictUpdatedEvent {
  type: "VerdictUpdated";
  payload: { pair: string; verdict: Record<string, unknown> };
}

export interface VerdictSnapshotEvent {
  type: "VerdictSnapshot";
  payload: { pair: string | null; verdicts: Record<string, Record<string, unknown>> };
}

export interface PipelineUpdatedEvent {
  type: "PipelineUpdated";
  payload: { pair: string; pipeline: Record<string, unknown> };
}

export interface PingEvent {
  type: "ping";
  ts?: number;
}

// ── Domain-specific WS endpoint events ─────────────────────────

export interface PriceUpdatedEvent {
  type: "PriceUpdated";
  payload: Record<string, unknown>;
}

export interface PricesSnapshotEvent {
  type: "PricesSnapshot";
  payload: Record<string, unknown>;
}

export interface RiskUpdatedEvent {
  type: "RiskUpdated";
  payload: Record<string, unknown>;
}

export interface SignalUpdatedEvent {
  type: "SignalUpdated";
  payload: Record<string, unknown>;
}

export interface TradeSnapshotEvent {
  type: "TradeSnapshot";
  payload: Record<string, unknown>;
}

export interface TradeUpdatedEvent {
  type: "TradeUpdated";
  payload: Record<string, unknown>;
}

export interface CandleSnapshotEvent {
  type: "CandleSnapshot";
  payload: Record<string, unknown>;
}

export interface CandleFormingEvent {
  type: "CandleForming";
  payload: Record<string, unknown>;
}

export interface EquityUpdatedEvent {
  type: "EquityUpdated";
  payload: Record<string, unknown>;
}

export interface AlertCreatedEvent {
  type: "AlertCreated";
  payload: Record<string, unknown>;
}

export interface AlertUpdatedEvent {
  type: "AlertUpdated";
  payload: Record<string, unknown>;
}

export type WsEvent =
  | PipelineResultUpdatedEvent
  | ExecutionStateUpdatedEvent
  | RiskStateUpdatedEvent
  | SystemStatusUpdatedEvent
  | PreferencesUpdatedEvent
  | VerdictUpdatedEvent
  | VerdictSnapshotEvent
  | PipelineUpdatedEvent
  | PingEvent
  | PriceUpdatedEvent
  | PricesSnapshotEvent
  | RiskUpdatedEvent
  | SignalUpdatedEvent
  | TradeSnapshotEvent
  | TradeUpdatedEvent
  | CandleSnapshotEvent
  | CandleFormingEvent
  | EquityUpdatedEvent
  | AlertCreatedEvent
  | AlertUpdatedEvent;
