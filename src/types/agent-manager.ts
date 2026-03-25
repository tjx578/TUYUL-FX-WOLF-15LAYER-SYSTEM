export enum EAClass {
  PRIMARY = "PRIMARY",
  PORTFOLIO = "PORTFOLIO",
}

export enum EASubtype {
  BROKER = "BROKER",
  PROP_FIRM = "PROP_FIRM",
  EDUMB = "EDUMB",
  STANDARD_REPORTER = "STANDARD_REPORTER",
}

export enum ExecutionMode {
  LIVE = "LIVE",
  DEMO = "DEMO",
  SHADOW = "SHADOW",
}

export enum ReporterMode {
  FULL = "FULL",
  BALANCE_ONLY = "BALANCE_ONLY",
  DISABLED = "DISABLED",
}

export enum AgentStatus {
  ONLINE = "ONLINE",
  WARNING = "WARNING",
  OFFLINE = "OFFLINE",
  QUARANTINED = "QUARANTINED",
  DISABLED = "DISABLED",
}

export interface AgentItem {
  id: string;
  agent_name: string;
  ea_class: EAClass;
  ea_subtype: EASubtype;
  execution_mode: ExecutionMode;
  reporter_mode: ReporterMode;
  status: AgentStatus;
  linked_account_id: string | null;
  linked_profile_id: string | null;
  mt5_login: number | null;
  mt5_server: string | null;
  broker_name: string | null;
  strategy_profile: string;
  risk_multiplier: number;
  news_lock_setting: string;
  safe_mode: boolean;
  locked: boolean;
  lock_reason: string | null;
  locked_at: string | null;
  locked_by: string | null;
  notes: string | null;
  version: string | null;
  created_at: string;
  updated_at: string;
  runtime?: AgentRuntime;
}

export interface AgentRuntime {
  agent_id: string;
  last_heartbeat: string | null;
  last_success: string | null;
  last_failure: string | null;
  failure_reason: string | null;
  trades_executed: number;
  trades_failed: number;
  uptime_seconds: number;
  cpu_usage_pct: number | null;
  memory_mb: number | null;
  connection_latency_ms: number | null;
  updated_at: string;
}

export interface AgentListResponse {
  agents: AgentItem[];
  total: number;
}

export interface AgentProfile {
  id: string;
  profile_name: string;
  description: string | null;
  ea_class: EAClass;
  ea_subtype: EASubtype;
  execution_mode: ExecutionMode;
  reporter_mode: ReporterMode;
  default_risk_multiplier: number;
  default_news_lock: string;
  allowed_strategies: string[];
  created_at: string;
  updated_at: string;
}

export interface AgentEvent {
  id: string;
  agent_id: string;
  event_type: string;
  severity: "INFO" | "WARNING" | "CRITICAL";
  message: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface AgentAuditLog {
  id: string;
  agent_id: string;
  action: string;
  performed_by: string;
  details: Record<string, unknown>;
  previous_state: Record<string, unknown> | null;
  new_state: Record<string, unknown> | null;
  created_at: string;
}

export interface PortfolioSnapshot {
  id: string;
  agent_id: string;
  account_id: string;
  balance: number;
  equity: number;
  margin_used: number;
  margin_free: number;
  open_positions: number;
  daily_pnl: number;
  floating_pnl: number;
  snapshot_source: string;
  captured_at: string;
}

export interface CreateAgentRequest {
  agent_name: string;
  ea_class: EAClass;
  ea_subtype: EASubtype;
  execution_mode?: ExecutionMode;
  reporter_mode?: ReporterMode;
  linked_account_id?: string;
  linked_profile_id?: string;
  mt5_login?: number;
  mt5_server?: string;
  broker_name?: string;
  strategy_profile?: string;
  risk_multiplier?: number;
  news_lock_setting?: string;
  notes?: string;
}

export interface UpdateAgentRequest {
  agent_name?: string;
  execution_mode?: ExecutionMode;
  reporter_mode?: ReporterMode;
  linked_account_id?: string | null;
  linked_profile_id?: string | null;
  mt5_login?: number | null;
  mt5_server?: string | null;
  broker_name?: string | null;
  strategy_profile?: string;
  risk_multiplier?: number;
  news_lock_setting?: string;
  safe_mode?: boolean;
  notes?: string | null;
}

export interface LockAgentRequest {
  reason: string;
  locked_by?: string;
}

export interface CreateProfileRequest {
  profile_name: string;
  description?: string;
  ea_class: EAClass;
  ea_subtype: EASubtype;
  execution_mode?: ExecutionMode;
  reporter_mode?: ReporterMode;
  default_risk_multiplier?: number;
  default_news_lock?: string;
  allowed_strategies?: string[];
}

export interface AgentListFilters {
  ea_class?: EAClass;
  status?: AgentStatus;
  limit?: number;
  offset?: number;
}
