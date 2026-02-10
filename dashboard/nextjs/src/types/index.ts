/**
 * TypeScript types matching L12 output schema
 */

export interface L12Verdict {
  schema: string;
  pair: string;
  timestamp: string;
  verdict: string;
  confidence: string;
  wolf_status: string;
  gates: {
    gate_1_tii: string;
    gate_2_integrity: string;
    gate_3_rr: string;
    gate_4_fta: string;
    gate_5_montecarlo: string;
    gate_6_propfirm: string;
    gate_7_drawdown: string;
    gate_8_latency: string;
    gate_9_conf12: string;
    passed: number;
    total: number;
  };
  execution: {
    direction: string | null;
    entry_zone: string | null;
    entry_price: number | null;
    stop_loss: number | null;
    take_profit_1: number | null;
    execution_mode: string;
    rr_ratio: number | null;
    lot_size: number | null;
    risk_percent: number | null;
    risk_amount: number | null;
  };
  scores: {
    wolf_30_point: number;
    f_score: number;
    t_score: number;
    fta_score: number;
    exec_score: number;
  };
  proceed_to_L13: boolean;
}

export interface SystemHealth {
  status: string;
  service: string;
  version: string;
  latency_ms?: number;
  redis?: boolean;
  feed_status?: string;
}

export interface ContextSnapshot {
  ticks: any[];
  candles: Record<string, any>;
  news: any;
  meta: Record<string, any>;
}

export interface ExecutionState {
  state: string;
  order: any;
  reason: string | null;
  timestamp: string | null;
}

export interface PairInfo {
  symbol: string;
  name: string;
  enabled: boolean;
}
