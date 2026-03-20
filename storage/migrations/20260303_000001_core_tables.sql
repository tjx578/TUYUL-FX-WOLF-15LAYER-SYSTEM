CREATE TABLE IF NOT EXISTS accounts (
  id UUID PRIMARY KEY,
  broker_account_id TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS account_states (
  id BIGSERIAL PRIMARY KEY,
  account_id UUID NOT NULL REFERENCES accounts(id),
  balance NUMERIC(18,2) NOT NULL,
  equity NUMERIC(18,2) NOT NULL,
  drawdown_pct NUMERIC(8,4) NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS prop_rules (
  id UUID PRIMARY KEY,
  profile_name TEXT NOT NULL,
  rule_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signals (
  id UUID PRIMARY KEY,
  symbol TEXT NOT NULL,
  verdict TEXT NOT NULL,
  confidence NUMERIC(6,4) NOT NULL,
  signal_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS allocations (
  id UUID PRIMARY KEY,
  signal_id UUID NOT NULL REFERENCES signals(id),
  account_id UUID NOT NULL REFERENCES accounts(id),
  allowed BOOLEAN NOT NULL,
  recommended_lot NUMERIC(12,4),
  reason TEXT,
  allocation_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trades (
  id UUID PRIMARY KEY,
  allocation_id UUID NOT NULL REFERENCES allocations(id),
  state TEXT NOT NULL,
  trade_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_logs (
  id BIGSERIAL PRIMARY KEY,
  event_type TEXT NOT NULL,
  entity_id TEXT,
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS config_profiles (
  id UUID PRIMARY KEY,
  profile_type TEXT NOT NULL,
  profile_name TEXT NOT NULL,
  config JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);