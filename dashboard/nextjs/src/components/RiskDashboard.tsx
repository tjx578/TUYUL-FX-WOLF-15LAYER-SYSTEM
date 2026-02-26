'use client';

/**
 * Risk Dashboard — real-time risk visualization.
 *
 * Displays:
 * - Drawdown gauges (daily/weekly/total)
 * - Circuit breaker state
 * - Prop firm compliance
 * - Position sizing info
 * - Open exposure tracking
 *
 * Uses WebSocket /ws/risk for live state + REST fallback.
 */

import { useRiskWS } from '@/lib/websocket';
import { useRiskSnapshot, useAccounts } from '@/lib/api';
import type { RiskSnapshot } from '@/types';
import clsx from 'clsx';
import { useState } from 'react';
import {
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
  Zap,
  TrendingDown,
  Activity,
  Lock,
  LockOpen,
} from 'lucide-react';

export default function RiskDashboard() {
  const { data: wsRisk, connected: wsConnected } = useRiskWS();
  const { data: accounts } = useAccounts();
  const [selectedAccount, setSelectedAccount] = useState<string | null>(null);
  const { data: snapshot } = useRiskSnapshot(selectedAccount || (accounts ?? [])[0]?.account_id || '');

  return (
    <div className="space-y-4">
      {/* Account Selector */}
      {(accounts ?? []).length > 0 && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500">Account:</span>
          {(accounts ?? []).map((acc) => (
            <button
              key={acc.account_id}
              onClick={() => setSelectedAccount(acc.account_id)}
              className={clsx(
                'px-3 py-1 rounded text-xs font-medium transition-colors',
                (selectedAccount || (accounts ?? [])[0]?.account_id) === acc.account_id
                  ? 'bg-wolf-gold/20 text-wolf-gold'
                  : 'text-gray-500 hover:text-gray-300 bg-wolf-gray/30'
              )}
            >
              {acc.account_name || acc.account_id}
            </button>
          ))}
        </div>
      )}

      {/* Top Row — Critical Indicators */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {/* Circuit Breaker */}
        <CircuitBreakerCard state={wsRisk ? { state: String(wsRisk), is_open: false } : undefined} />

        {/* Trading Allowed */}
        <TradingStatusCard snapshot={snapshot} />

        {/* Account Summary */}
        <AccountSummaryCard snapshot={snapshot} />
      </div>

      {/* Drawdown Gauges */}
      <div className="rounded-lg border border-wolf-gray bg-wolf-dark/50 p-4">
        <h3 className="text-sm font-bold text-gray-200 mb-3 flex items-center gap-2">
          <TrendingDown className="w-4 h-4 text-red-400" />
          Drawdown Monitor
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <DrawdownGauge
            label="Daily"
            current={snapshot?.daily_dd_percent ?? 0}
            limit={snapshot?.daily_dd_limit ?? 5}
          />
          <DrawdownGauge
            label="Weekly"
            current={0}
            limit={8}
          />
          <DrawdownGauge
            label="Total"
            current={snapshot?.total_dd_percent ?? 0}
            limit={snapshot?.total_dd_limit ?? 10}
          />
        </div>
      </div>

      {/* Risk Details Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {/* Prop Firm Compliance */}
        <PropFirmCard snapshot={snapshot} />

        {/* Risk Multiplier */}
        <RiskMultiplierCard snapshot={snapshot} />
      </div>

      <div className="flex items-center gap-2 text-xs text-gray-500">
        <div className={clsx(
          'w-1.5 h-1.5 rounded-full',
          wsConnected ? 'bg-emerald-400' : 'bg-red-400'
        )} />
        Risk WS: {wsConnected ? 'connected' : 'disconnected'}
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function CircuitBreakerCard({ state }: { state: { state: string; is_open: boolean } | undefined }) {
  const cbState = state?.state || 'UNKNOWN';
  const isOpen = state?.is_open ?? false;

  const stateConfig: Record<string, { color: string; bg: string; icon: any }> = {
    CLOSED: { color: 'text-emerald-400', bg: 'bg-emerald-900/20 border-emerald-800/30', icon: ShieldCheck },
    OPEN: { color: 'text-red-400', bg: 'bg-red-900/20 border-red-800/30', icon: ShieldAlert },
    HALF_OPEN: { color: 'text-yellow-400', bg: 'bg-yellow-900/20 border-yellow-800/30', icon: AlertTriangle },
    UNKNOWN: { color: 'text-gray-500', bg: 'bg-wolf-gray/20 border-wolf-gray', icon: Activity },
  };

  const cfg = stateConfig[cbState] || stateConfig.UNKNOWN;
  const Icon = cfg.icon;

  return (
    <div className={clsx('rounded-lg border p-4', cfg.bg)}>
      <div className="flex items-center gap-2 mb-2">
        <Icon className={clsx('w-5 h-5', cfg.color)} />
        <span className="text-xs uppercase tracking-wider text-gray-400">Circuit Breaker</span>
      </div>
      <div className={clsx('text-2xl font-bold font-mono', cfg.color)}>
        {cbState}
      </div>
      <p className="text-xs text-gray-500 mt-1">
        {isOpen ? 'Trading halted — cooldown active' : 'Normal operation'}
      </p>
    </div>
  );
}

function TradingStatusCard({ snapshot }: { snapshot: any }) {
  const allowed = snapshot?.is_trading_allowed ?? true;

  return (
    <div className={clsx(
      'rounded-lg border p-4',
      allowed
        ? 'bg-emerald-900/20 border-emerald-800/30'
        : 'bg-red-900/20 border-red-800/30'
    )}>
      <div className="flex items-center gap-2 mb-2">
        {allowed ? (
          <Unlock className="w-5 h-5 text-emerald-400" />
        ) : (
          <Lock className="w-5 h-5 text-red-400" />
        )}
        <span className="text-xs uppercase tracking-wider text-gray-400">Trading Status</span>
      </div>
      <div className={clsx('text-2xl font-bold', allowed ? 'text-emerald-400' : 'text-red-400')}>
        {allowed ? 'ALLOWED' : 'BLOCKED'}
      </div>
      <p className="text-xs text-gray-500 mt-1">
        Open trades: {snapshot?.open_trades ?? 0} / {snapshot?.max_concurrent_trades ?? '—'}
      </p>
    </div>
  );
}

function AccountSummaryCard({ snapshot }: { snapshot: any }) {
  return (
    <div className="rounded-lg border border-wolf-gray bg-wolf-dark/50 p-4">
      <div className="flex items-center gap-2 mb-2">
        <Activity className="w-5 h-5 text-wolf-gold" />
        <span className="text-xs uppercase tracking-wider text-gray-400">Account</span>
      </div>
      <div className="space-y-1">
        <div className="flex justify-between">
          <span className="text-xs text-gray-500">Balance</span>
          <span className="text-sm font-mono font-bold text-gray-200">
            ${(snapshot?.balance ?? 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-xs text-gray-500">Equity</span>
          <span className="text-sm font-mono font-bold text-gray-200">
            ${(snapshot?.equity ?? 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-xs text-gray-500">Risk Mult.</span>
          <span className="text-sm font-mono text-wolf-gold">
            {(snapshot?.risk_multiplier ?? 1.0).toFixed(2)}x
          </span>
        </div>
      </div>
    </div>
  );
}

function DrawdownGauge({
  label,
  current,
  limit,
}: {
  label: string;
  current: number;
  limit: number;
}) {
  const pct = limit > 0 ? Math.min((current / limit) * 100, 100) : 0;
  const isWarning = pct >= 60;
  const isCritical = pct >= 80;

  const barColor = isCritical
    ? 'bg-red-500'
    : isWarning
    ? 'bg-yellow-500'
    : 'bg-emerald-500';

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-gray-400">{label}</span>
        <span className={clsx(
          'text-xs font-mono font-bold',
          isCritical ? 'text-red-400' : isWarning ? 'text-yellow-400' : 'text-emerald-400'
        )}>
          {current.toFixed(2)}% / {limit.toFixed(1)}%
        </span>
      </div>
      <div className="h-3 rounded-full bg-wolf-gray/50 overflow-hidden">
        <div
          className={clsx('h-full rounded-full transition-all duration-500', barColor)}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function PropFirmCard({ snapshot }: { snapshot: any }) {
  const firm = snapshot?.prop_firm;

  return (
    <div className="rounded-lg border border-wolf-gray bg-wolf-dark/50 p-4">
      <h3 className="text-sm font-bold text-gray-200 mb-3 flex items-center gap-2">
        <Zap className="w-4 h-4 text-wolf-gold" />
        Prop Firm Guard
      </h3>
      {firm ? (
        <div className="space-y-2 text-xs">
          <div className="flex justify-between">
            <span className="text-gray-500">Firm</span>
            <span className="text-gray-200 font-medium">{firm}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">Max Daily DD</span>
            <span className="text-gray-200 font-mono">{snapshot?.max_daily_dd_limit?.toFixed(1)}%</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">Max Total DD</span>
            <span className="text-gray-200 font-mono">{snapshot?.max_total_dd_limit?.toFixed(1)}%</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">Max Concurrent</span>
            <span className="text-gray-200 font-mono">{snapshot?.max_concurrent_trades}</span>
          </div>
        </div>
      ) : (
        <p className="text-xs text-gray-500">No prop firm profile configured</p>
      )}
    </div>
  );
}

function RiskMultiplierCard({ snapshot }: { snapshot: any }) {
  const multiplier = snapshot?.risk_multiplier ?? 1.0;

  return (
    <div className="rounded-lg border border-wolf-gray bg-wolf-dark/50 p-4">
      <h3 className="text-sm font-bold text-gray-200 mb-3 flex items-center gap-2">
        <Activity className="w-4 h-4 text-wolf-blue" />
        Risk Multiplier
      </h3>
      <div className="space-y-2">
        <div className="flex items-end gap-2">
          <span className={clsx(
            'text-3xl font-bold font-mono',
            multiplier >= 1.0 ? 'text-emerald-400' : multiplier >= 0.5 ? 'text-yellow-400' : 'text-red-400'
          )}>
            {multiplier.toFixed(2)}x
          </span>
          <span className="text-xs text-gray-500 mb-1">effective risk scaling</span>
        </div>
      </div>
    </div>
  );
}
