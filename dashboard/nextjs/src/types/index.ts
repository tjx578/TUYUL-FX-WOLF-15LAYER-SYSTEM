/**
 * TypeScript types matching backend data contracts.
 */

// ---------------------------------------------------------------------------
// L12 Verdict
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// System Health
// ---------------------------------------------------------------------------

export interface SystemHealth {
  status: string;
  service: string;
  version: string;
  latency_ms?: number;
  redis?: boolean;
  feed_status?: string;
}

// ---------------------------------------------------------------------------
// Context Snapshot
// ---------------------------------------------------------------------------

export interface ContextSnapshot {
  ticks: any[];
  candles: Record<string, any>;
  news: any;
  meta: Record<string, any>;
}

// ---------------------------------------------------------------------------
// Execution State
// ---------------------------------------------------------------------------

export interface ExecutionState {
  state: string;
  order: any;
  reason: string | null;
  timestamp: string | null;
}

// ---------------------------------------------------------------------------
// Pair Info
// ---------------------------------------------------------------------------

export interface PairInfo {
  symbol: string;
  name: string;
  enabled: boolean;
}

// ---------------------------------------------------------------------------
// Trade (matches backend Trade model)
// ---------------------------------------------------------------------------

export type TradeStatus =
  | 'INTENDED'
  | 'PENDING'
  | 'OPEN'
  | 'CLOSED'
  | 'CANCELLED'
  | 'SKIPPED';

export interface TradeLeg {
  leg_number: number;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  lot_size: number;
  status: string;
}

export interface Trade {
  trade_id: string;
  signal_id: string;
  account_id: string;
  pair: string;
  direction: string;
  status: TradeStatus;
  risk_mode?: string;
  risk_percent?: number;
  risk_amount?: number;
  legs?: TradeLeg[];
  created_at?: string;
  updated_at?: string;
  closed_at?: string;
  close_reason?: string;
  pnl?: number;
  pnl_pips?: number;
}

// ---------------------------------------------------------------------------
// Journal Entries (J1-J4)
// ---------------------------------------------------------------------------

export interface JournalEntry {
  type: 'J1' | 'J2' | 'J3' | 'J4';
  pair: string;
  timestamp: string;
  data: Record<string, any>;
}

export interface JournalMetrics {
  total_signals: number;
  executed: number;
  rejected: number;
  rejection_rate: number;
  protection_rate: number;
  win_rate: number;
  avg_rr: number;
  total_pnl: number;
}

export interface DailyJournal {
  date: string;
  entries: JournalEntry[];
  metrics: JournalMetrics;
}

// ---------------------------------------------------------------------------
// Risk State
// ---------------------------------------------------------------------------

export interface RiskSnapshot {
  account_id: string;
  balance: number;
  equity: number;
  daily_dd_percent: number;
  weekly_dd_percent: number;
  total_dd_percent: number;
  open_trades: number;
  max_concurrent_trades: number;
  circuit_breaker_state: string;
  is_trading_allowed: boolean;
  risk_multiplier: number;
  prop_firm?: string;
  max_daily_dd_limit: number;
  max_total_dd_limit: number;
}

export interface DrawdownData {
  daily_dd: number;
  daily_dd_limit: number;
  weekly_dd: number;
  weekly_dd_limit: number;
  total_dd: number;
  total_dd_limit: number;
  high_water_mark: number;
  current_equity: number;
}

export interface CircuitBreakerState {
  state: 'CLOSED' | 'OPEN' | 'HALF_OPEN';
  is_open: boolean;
  reason?: string;
  cooldown_until?: string;
  consecutive_losses?: number;
}

// ---------------------------------------------------------------------------
// Account
// ---------------------------------------------------------------------------

export interface Account {
  account_id: string;
  name: string;
  balance: number;
  equity: number;
  prop_firm?: string;
  max_daily_dd_percent: number;
  max_total_dd_percent: number;
  max_concurrent_trades: number;
}
