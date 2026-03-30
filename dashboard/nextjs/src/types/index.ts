// ============================================================
// TUYUL FX Wolf-15 — TypeScript Type Definitions
// Mirrors: dashboard/backend/schemas.py + schemas/trade_models.py
// ============================================================

// ─── ENUMS ───────────────────────────────────────────────────

export enum TradeStatus {
  INTENDED = "INTENDED",
  PENDING = "PENDING",
  OPEN = "OPEN",
  CLOSED = "CLOSED",
  CANCELLED = "CANCELLED",
  SKIPPED = "SKIPPED",
}

export enum CloseReason {
  TP_HIT = "TP_HIT",
  SL_HIT = "SL_HIT",
  MANUAL_CLOSE = "MANUAL_CLOSE",
  SYSTEM_PROTECTION = "SYSTEM_PROTECTION",
  EXPIRY = "EXPIRY",
  NEWS_LOCK = "NEWS_LOCK",
  M15_INVALIDATION = "M15_INVALIDATION",
}

export enum TradeSource {
  EA = "EA",
  MANUAL = "MANUAL",
}

export enum RiskMode {
  FIXED = "FIXED",
  SPLIT = "SPLIT",
}

export enum RiskSeverity {
  SAFE = "SAFE",
  WARNING = "WARNING",
  CRITICAL = "CRITICAL",
}

export enum ScalingModel {
  FIXED = "FIXED",
  CONFIDENCE = "CONFIDENCE",
  STEP = "STEP",
}

export enum VerdictType {
  EXECUTE = "EXECUTE",
  EXECUTE_BUY = "EXECUTE_BUY",
  EXECUTE_SELL = "EXECUTE_SELL",
  EXECUTE_REDUCED_RISK = "EXECUTE_REDUCED_RISK",
  NO_TRADE = "NO_TRADE",
  HOLD = "HOLD",
  ABORT = "ABORT",
}

export enum CircuitBreakerState {
  CLOSED = "CLOSED",
  HALF_OPEN = "HALF_OPEN",
  OPEN = "OPEN",
}

// ─── L12 VERDICT ─────────────────────────────────────────────

export interface GateCheck {
  passed: boolean;
  gate_id: string;
  name: string;
  value?: number | string;
  threshold?: number | string;
  message?: string;
}

export interface L12Scores {
  wolf_score: number;
  tii_score: number;
  frpc_score: number;
  regime: string;
  session: string;
  confluence_score?: number;
  volume_profile_score?: number;
  // Wolf 30-point breakdown (L4)
  f_score?: number;     // Fundamental 0-8
  t_score?: number;     // Technical 0-12
  fta_score?: number;   // Alignment 0-5
  exec_score?: number;  // Execution 0-5
}

export interface L12Verdict {
  symbol: string;
  verdict: VerdictType;
  confidence: number;
  direction?: "BUY" | "SELL";
  entry_price?: number;
  stop_loss?: number;
  take_profit_1?: number;
  take_profit_2?: number;
  risk_reward_ratio?: number;
  gates: GateCheck[];
  scores?: L12Scores;
  timestamp: number;
  expires_at?: number;
  wolf_status?: string;
  session?: string;
}

// ─── SIGNAL ──────────────────────────────────────────────────

export interface Layer12Signal {
  signal_id: string;
  timestamp: number;
  pair: string;
  direction: "BUY" | "SELL";
  entry: number;
  stop_loss: number;
  take_profit_1: number;
  rr: number;
  verdict: VerdictType;
  confidence: number;
  wolf_score: number;
  tii_sym: number;
  frpc: number;
  scores?: L12Scores;
  expires_at?: number;
}

// ─── TRADE ───────────────────────────────────────────────────

export interface TradeLeg {
  leg: number;
  entry: number;
  sl: number;
  tp: number;
  lot: number;
  status: TradeStatus;
  open_price?: number;
  close_price?: number;
  pnl?: number;
  opened_at?: string;
  closed_at?: string;
}

export interface Trade {
  risk_percent: number;
  trade_id: string;
  signal_id: string;
  account_id: string;
  pair: string;
  direction: "BUY" | "SELL";
  status: TradeStatus;
  source: TradeSource;
  risk_mode: RiskMode;
  total_risk_percent: number;
  total_risk_amount: number;
  lot_size: number;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  legs: TradeLeg[];
  created_at: string;
  updated_at: string;
  opened_at?: string;
  closed_at?: string;
  close_reason?: CloseReason;
  pnl?: number;
  pnl_percent?: number;
}

// ─── ACCOUNT ─────────────────────────────────────────────────

export interface Account {
  id: string;
  name: string;
  label: string;
  account_id: string;
  broker: string;
  account_name: string;
  balance: number;
  equity: number;
  equity_high: number;
  currency: string;
  prop_firm: boolean;
  prop_firm_code?: string;
  daily_dd_percent: number;
  total_dd_percent: number;
  open_risk_percent: number;
  open_trades: number;
  risk_state: RiskSeverity;
  max_daily_dd_percent: number;
  max_total_dd_percent: number;
  max_concurrent_trades: number;
  data_source?: string;
  compliance_mode?: boolean;
  created_at?: string;
  // Capital deployment fields
  readiness_score?: number;
  usable_capital?: number;
  eligibility_flags?: EligibilityFlags;
  lock_reasons?: string[];
  is_archived?: boolean;
}

export interface EligibilityFlags {
  compliance_ok: boolean;
  circuit_breaker_ok: boolean;
  not_locked: boolean;
  no_news_lock: boolean;
  daily_dd_ok: boolean;
  total_dd_ok: boolean;
  slots_available: boolean;
  ea_linked: boolean;
}

export interface CapitalDeploymentResponse {
  count: number;
  total_usable_capital: number;
  avg_readiness_score: number;
  accounts: Account[];
}

export interface AccountCreate {
  broker: string;
  account_name: string;
  balance: number;
  equity: number;
  currency: string;
  data_source?: "MANUAL" | "EA";
  prop_firm?: boolean;
  prop_firm_code?: string | null;
  program_code?: string | null;
  phase_code?: string | null;
  reason?: string;
}

export interface CreateAccountRequest {
  account_name: string;
  broker: string;
  currency: string;
  starting_balance: number;
  current_balance: number;
  equity: number;
  equity_high: number;
  leverage: number;
  commission_model: string;
  notes: string;
  data_source: string;
  prop_firm: boolean;
  prop_firm_code: string | null;
  program_code: string | null;
  phase_code: string | null;
  compliance_mode: boolean;
  max_daily_dd_percent: number;
  max_total_dd_percent: number;
  max_concurrent_trades: number;
  reason: string;
}

// ─── RISK ─────────────────────────────────────────────────────

export interface RiskProfile {
  risk_per_trade_percent: number;
  max_daily_risk_percent: number;
  max_total_dd_percent: number;
  max_open_trades: number;
  confidence_scaling: boolean;
  scaling_model: ScalingModel;
}

export interface RiskCalculationResult {
  trade_allowed: boolean;
  recommended_lot: number;
  max_safe_lot: number;
  risk_used_percent: number;
  daily_dd_after: number;
  total_dd_after?: number;
  severity: RiskSeverity;
  reason?: string;
  split_lots?: number[];
}

export interface RiskSnapshot {
  can_trade: boolean;
  block_reason: string;
  account_id: string;
  daily_dd_percent: number;
  daily_dd_limit: number;
  total_dd_percent: number;
  total_dd_limit: number;
  open_risk_percent: number;
  open_trades: number;
  circuit_breaker: CircuitBreakerState;
  severity: RiskSeverity;
  timestamp: number;
}

export interface DrawdownData {
  timestamp: number;
  equity: number;
  balance: number;
  daily_dd: number;
  total_dd: number;
}

// ─── PROP FIRM ────────────────────────────────────────────────

export interface PropFirmGuardResult {
  allowed: boolean;
  code: string;
  severity: RiskSeverity;
  details: string;
  max_safe_lot?: number;
  violations?: string[];
}

export interface PropFirmStatus {
  allowed: boolean;
  code: string;
  details?: string;
}

export interface ProbabilityCalibration {
  grade: string;
  score: number;
  details?: string[];
}

// ─── JOURNAL ─────────────────────────────────────────────────

export interface JournalEntry {
  entry_id: string;
  signal_id: string;
  pair: string;
  direction?: "BUY" | "SELL";
  action: "TAKE" | "SKIP" | "OPEN" | "CLOSE";
  reason?: string;
  outcome?: "WIN" | "LOSS" | "BREAKEVEN";
  pnl?: number;
  rr_achieved?: number;
  timestamp: string;
  journal_type: "J1" | "J2" | "J3" | "J4";
}

export interface JournalMetrics {
  win_rate: number;
  rejection_rate: number;
  avg_rr: number;
  total_pnl: number;
  total_trades: number;
  total_wins: number;
  total_losses: number;
  total_skipped: number;
  best_pair?: string;
  worst_pair?: string;
  profit_factor?: number;
  expectancy?: number;
}

export interface DailyJournal {
  date: string;
  entries: JournalEntry[];
  metrics: JournalMetrics;
  net_pnl: number;
  sessions: string[];
}

// ─── PRICES ──────────────────────────────────────────────────

export interface PriceData {
  symbol: string;
  bid: number;
  ask: number;
  spread: number;
  timestamp: number;
  change_24h?: number;
  change_percent_24h?: number;
}

export interface CandleData {
  symbol: string;
  timeframe: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
  timestamp: number;
}

// ─── SYSTEM ───────────────────────────────────────────────────

export type FeedStatus = "fresh" | "stale_preserved" | "no_producer" | "no_transport" | "config_error";

/** Approved pipeline-wide freshness class labels (matches backend FreshnessClass enum). */
export type FreshnessClassLabel =
  | "LIVE"
  | "DEGRADED_BUT_REFRESHING"
  | "STALE_PRESERVED"
  | "NO_PRODUCER"
  | "NO_TRANSPORT"
  | "CONFIG_ERROR";

export interface SystemHealth {
  status: "ok" | "degraded" | "error";
  service: string;
  version: string;
  redis_connected: boolean;
  mt5_connected: boolean;
  active_pairs: number;
  active_trades: number;
  feed_status?: FeedStatus;
  freshness_class?: FreshnessClassLabel;
  feed_staleness_seconds?: number;
  feed_threshold_seconds?: number;
  feed_last_seen_ts?: number | null;
  detail?: string;
  producer_heartbeat_age_seconds?: number | null;
  producer_alive?: boolean;
  engine_heartbeat_age_seconds?: number | null;
  engine_alive?: boolean;
  uptime_seconds?: number;
  last_verdict_at?: number;
  timestamp?: number | string;
}

export interface OrchestratorState {
  mode: string;
  reason: string;
  compliance_code: string;
  updated_at?: string;
  event?: string;
  orchestrator_heartbeat_age_seconds?: number | null;
  orchestrator_ready?: boolean;
}

export interface ContextSnapshot {
  session: string;
  regime: string;
  volatility: string;
  trend: string;
  active_pairs: number;
  timestamp: number;
}

export interface ExecutionState {
  state: "IDLE" | "SCANNING" | "SIGNAL_READY" | "EXECUTING" | "COOLDOWN";
  current_pair?: string;
  signal_count: number;
  last_execution?: string;
  cooldown_until?: number;
}

export interface PairInfo {
  symbol: string;
  category: string;
  pip_value: number;
  active: boolean;
  last_verdict?: VerdictType;
  last_confidence?: number;
}

// ─── PROBABILITY ──────────────────────────────────────────────

export interface ProbabilityMetrics {
  signal_id: string;
  pair: string;
  mc_win_probability: number;
  mc_loss_probability: number;
  bayesian_confidence: number;
  calibration_grade: "A" | "B" | "C" | "D" | "F";
  expected_rr: number;
  simulations_run: number;
  timestamp: number;
}

export interface ProbabilitySummary {
  total_signals_today: number;
  avg_mc_win_prob: number;
  avg_bayesian_confidence: number;
  calibration_grade: "A" | "B" | "C" | "D" | "F";
  high_confidence_signals: number;
  low_confidence_signals: number;
}

// ─── ALERTS ───────────────────────────────────────────────────

export type AlertType =
  | "ORDER_PLACED"
  | "ORDER_FILLED"
  | "ORDER_CANCELLED"
  | "SYSTEM_VIOLATION"
  | "RISK_LIMIT_REACHED"
  | "PROP_FIRM_BREACH"
  | "CIRCUIT_BREAKER_OPEN"
  | "NEWS_LOCK"
  | "SESSION_CHANGE";

export interface AlertEvent {
  alert_id: string;
  type: AlertType;
  severity: "INFO" | "WARNING" | "CRITICAL";
  message: string;
  pair?: string;
  trade_id?: string;
  timestamp: string;
}

// ─── EA BRIDGE ────────────────────────────────────────────────

export interface ExecutionCommand {
  command_id: string;
  signal_id: string;
  type: "PLACE_PENDING" | "CANCEL_ORDER" | "SYNC_STATE";
  symbol: string;
  direction: "BUY" | "SELL";
  order_type: "LIMIT" | "STOP" | "MARKET";
  entry: number;
  sl: number;
  tp: number;
  lot_size: number;
  expiry?: number;
}

// ─── API RESPONSE WRAPPERS ────────────────────────────────────

export interface ApiResponse<T> {
  data?: T;
  error?: string;
  status: number;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  per_page: number;
}

/** @deprecated Use {@link https://github.com/tjx578/TUYUL-FX-WOLF-15LAYER-SYSTEM} AgentListResponse from @/types/agent-manager instead. Sunset: 2026-06-01 */
export interface EAStatus {
  healthy: boolean;
  running: boolean;
  engine_state: string;
  queue_depth: number;
  queue_max: number;
  safe_mode: boolean;
  agents_total: number;
  agents_connected: number;
  total_failures: number;
  recent_failures: AgentFailure[];
  cooldown_active: boolean;
  updated_at: string;
}

export interface AgentFailure {
  agent_id: string;
  reason: string;
  at: string;
}

/** @deprecated Use AgentItem from @/types/agent-manager instead. Sunset: 2026-06-01 */
export interface EAAgent {
  agent_id: string;
  account_id: string;
  profile: string;
  status: "connected" | "disconnected" | "degraded" | "cooldown";
  healthy: boolean;
  last_heartbeat: string;
  last_success: string;
  last_failure: string;
  failure_reason: string;
  trades_executed: number;
  trades_failed: number;
  uptime_seconds: number;
  version: string;
  scope: string;
}

/** @deprecated Use AgentEvent from @/types/agent-manager instead. Sunset: 2026-06-01 */
export interface EALog {
  id: string;
  timestamp: string;
  level: string;
  message: string;
  agent_id?: string;
}

export interface PropFirmPhase {
  phase_name: string;
  progress_percent: number;
}

export interface CalendarEvent {
  id?: string;
  time: string;
  currency: string;
  impact: "LOW" | "MEDIUM" | "HIGH";
  event?: string;
  canonical_id?: string;
  title?: string;
  date?: string;
  datetime_utc?: string | null;
  is_timeless?: boolean;
  minutes_away?: number | null;
  is_imminent?: boolean;
  source?: string;
  actual?: string | null;
  forecast?: string | null;
  previous?: string | null;
}

export interface CalendarDayResponse {
  date: string;
  total: number;
  high_impact_count: number;
  news_lock: {
    active: boolean;
    reason?: string | null;
  };
  events: CalendarEvent[];
}

export interface CalendarUpcomingResponse {
  hours_ahead: number;
  impact_filter?: string | null;
  count: number;
  events: CalendarEvent[];
  has_high_impact: boolean;
}

export interface CalendarBlockerResponse {
  is_locked: boolean;
  lock_reason?: string;
  upcoming_count: number;
  checked_at?: string | null;
  upcoming: CalendarEvent[];
}

export interface SourceHealthRecord {
  source: string;
  healthy: boolean;
  last_checked?: string | null;
  last_success?: string | null;
  last_error?: string | null;
}

export interface CalendarHealthResponse {
  sources: Record<string, SourceHealthRecord>;
  checked_at: string;
}
