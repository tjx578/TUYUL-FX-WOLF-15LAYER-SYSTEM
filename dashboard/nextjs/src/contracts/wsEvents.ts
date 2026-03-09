import type { ExecutionStateUpdatedPayload } from "./execution";
import type { PipelineResultView } from "./pipelineResult";
import type { OperatorPreferences } from "./preferences";

export interface RiskStateView {
  account_id: string;
  dd_pct: number;
}

export interface SystemStatusView {
  mode: "NORMAL" | "DEGRADED";
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

export type WsEvent =
  | PipelineResultUpdatedEvent
  | ExecutionStateUpdatedEvent
  | RiskStateUpdatedEvent
  | SystemStatusUpdatedEvent
  | PreferencesUpdatedEvent;
