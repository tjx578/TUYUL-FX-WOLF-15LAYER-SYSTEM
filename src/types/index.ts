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
    f_score?: number;
    t_score?: number;
    fta_score?: number;
    exec_score?: number;
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
    account_id: string;
    label: string;
    broker?: string;
    account_name?: string;
}

export interface AlertEvent {
    alert_id?: string;
    event_id: string;
    trade_id?: string;
    account_id?: string;
    pair?: string;
    type: string;
    severity: "INFO" | "WARNING" | "CRITICAL";
    title?: string;
    message: string;
    timestamp: number | string;
}

export type FeedStatus = "fresh" | "stale_preserved" | "no_producer" | "no_transport" | "config_error";

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

export interface EAAgent {
    agent_id: string;
    account_id?: string;
    profile?: string;
    status: "connected" | "degraded" | "disconnected" | "cooldown";
    version?: string;
    last_heartbeat?: string;
    last_success?: string;
    last_failure?: string;
    failure_reason?: string;
    trades_executed: number;
    trades_failed: number;
    uptime_seconds: number;
}
