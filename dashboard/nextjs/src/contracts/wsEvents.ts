import type { ExecutionStateUpdatedPayload } from "./execution";
import type { PipelineResultView } from "./pipelineResult";

export interface RiskStateView {
  account_id: string;
  dd_pct: number;
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

export type WsEvent =
  | PipelineResultUpdatedEvent
  | ExecutionStateUpdatedEvent
  | RiskStateUpdatedEvent;
