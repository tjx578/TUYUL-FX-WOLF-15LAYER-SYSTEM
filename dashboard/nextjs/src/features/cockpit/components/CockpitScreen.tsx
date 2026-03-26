"use client";

import { useMemo, useState } from "react";
import PageComplianceBanner from "@/components/feedback/PageComplianceBanner";
import { PipelinePanel } from "@/components/panels/PipelinePanel";
import { useAccounts, useAccountsRiskSnapshot } from "@/features/accounts/api/accounts.api";
import { useAllVerdicts } from "@/features/signals/api/verdicts.api";
import { useClock } from "@/hooks/useClock";
import { formatTime } from "@/lib/timezone";
import { useContext as useMarketContext } from "@/shared/api/system.api";
import { DomainHeader } from "@/shared/ui/DomainHeader";
import type { Account } from "@/types";

function toPortfolioRow(
  account: Account,
  snap?: {
    account_id: string;
    daily_dd_percent: number;
    total_dd_percent: number;
    open_trades: number;
    open_risk_percent: number;
  },
) {
  return {
    id: account.account_id,
    name: account.account_name ?? account.account_id,
    currency: account.currency ?? "USD",
    balance: account.balance,
    equity: account.equity ?? account.balance,
    dailyDD: snap?.daily_dd_percent ?? account.daily_dd_percent ?? 0,
    totalDD: snap?.total_dd_percent ?? account.total_dd_percent ?? 0,
    openTrades: snap?.open_trades ?? account.open_trades ?? 0,
    openRisk: snap?.open_risk_percent ?? account.open_risk_percent ?? 0,
  };
}

export function CockpitScreen() {
  const { data: rawAccounts, isLoading } = useAccounts();
  const { data: riskSnaps } = useAccountsRiskSnapshot();
  const { data: market } = useMarketContext();
  const { data: verdicts } = useAllVerdicts({ refreshInterval: 15_000 });
  const now = useClock();
  const [selectedId, setSelectedId] = useState("");

  const accounts = useMemo(() => {
    if (!rawAccounts) return [];
    return rawAccounts.map((account) => {
      const snap = riskSnaps?.find((risk) => risk.account_id === account.account_id);
      return toPortfolioRow(account, snap);
    });
  }, [rawAccounts, riskSnaps]);

  const active = accounts.find((account) => account.id === selectedId) ?? accounts[0];

  const verdictCount = verdicts?.length ?? 0;
  const contextLabel = [market?.regime ?? "—", market?.volatility ?? "—", market?.trend ?? "—"].join(" • ");

  if (isLoading) {
    return <div style={{ padding: 24 }}>Loading cockpit...</div>;
  }

  if (!active) {
    return <div style={{ padding: 24 }}>No accounts configured.</div>;
  }

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <PageComplianceBanner page="cockpit" />

      <DomainHeader
        domain="cockpit"
        title="PORTFOLIO COCKPIT"
        subtitle="Read-mostly operational overview across portfolio, pipeline, and governance state"
        actions={
          <div
            style={{
              fontSize: 11,
              color: "var(--text-muted)",
              fontFamily: "var(--font-mono)",
            }}
          >
            {formatTime(now)}
          </div>
        }
      />

      <div
        className="rounded-xl border p-3"
        style={{ display: "flex", gap: 16, flexWrap: "wrap", fontSize: 12 }}
      >
        <div>Market: {contextLabel}</div>
        <div>Verdicts: {verdictCount}</div>
        <div>Accounts: {accounts.length}</div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "300px 1fr 320px", gap: 16 }}>
        <aside className="rounded-xl border p-4" style={{ display: "grid", gap: 10 }}>
          <div className="font-semibold">Portfolio</div>
          {accounts.map((account) => (
            <button
              key={account.id}
              onClick={() => setSelectedId(account.id)}
              className="rounded-lg border px-3 py-2 text-left"
              style={{
                borderColor:
                  active.id === account.id ? "var(--accent, #00E5FF)" : "rgba(255,255,255,0.12)",
              }}
            >
              <div style={{ fontWeight: 700 }}>{account.name}</div>
              <div style={{ fontSize: 12, opacity: 0.8 }}>
                Eq {account.equity} • DD {account.dailyDD.toFixed(2)}%
              </div>
            </button>
          ))}
        </aside>

        <main style={{ display: "grid", gap: 16 }}>
          <div className="rounded-xl border p-4">
            <div className="font-semibold">Pipeline Runtime</div>
            <div style={{ marginTop: 12 }}>
              <PipelinePanel pair="EURUSD" />
            </div>
          </div>

          <div className="rounded-xl border p-4">
            <div className="font-semibold">Selected Account</div>
            <div
              style={{
                marginTop: 8,
                display: "grid",
                gridTemplateColumns: "repeat(4,1fr)",
                gap: 12,
              }}
            >
              <Metric label="Balance" value={String(active.balance)} />
              <Metric label="Equity" value={String(active.equity)} />
              <Metric label="Daily DD" value={`${active.dailyDD.toFixed(2)}%`} />
              <Metric label="Open Trades" value={String(active.openTrades)} />
            </div>
          </div>
        </main>

        <aside style={{ display: "grid", gap: 16 }}>
          <div className="rounded-xl border p-4">
            <div className="font-semibold">Risk Snapshot</div>
            <div style={{ marginTop: 8, display: "grid", gap: 6 }}>
              <div>Total DD: {active.totalDD.toFixed(2)}%</div>
              <div>Open Risk: {active.openRisk.toFixed(2)}%</div>
              <div>Currency: {active.currency}</div>
            </div>
          </div>

          <div className="rounded-xl border p-4">
            <div className="font-semibold">Governance</div>
            <div style={{ marginTop: 8, display: "grid", gap: 6 }}>
              <div>Execution remains Layer-12 authoritative.</div>
              <div>Cockpit is read-mostly and monitoring-focused.</div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border p-3">
      <div style={{ fontSize: 10, opacity: 0.7 }}>{label}</div>
      <div style={{ fontWeight: 700, marginTop: 4 }}>{value}</div>
    </div>
  );
}
