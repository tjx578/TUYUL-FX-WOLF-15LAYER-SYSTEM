"use client";

// ============================================================
// TUYUL FX Wolf-15 — Account Panel Components
// Exports: AccountCard, CreateAccountForm
// Used by: /accounts page
// ============================================================

import { useState } from "react";
import type { Account, AccountCreate } from "@/types";
import { createAccount } from "@/lib/api";
import Panel from "@/components/ui/Panel";
import StatusBadge from "@/components/ui/StatusBadge";
import { useLivePulse } from "@/hooks/useLivePulse";
import { formatNumber } from "@/lib/formatters";

// ─── ACCOUNT CARD ─────────────────────────────────────────────

interface AccountCardProps {
  account: Account;
  selected: boolean;
  onClick: () => void;
}

function accountGlow(riskState: string, selected: boolean): "cyan" | "emerald" | "orange" | "none" {
  if (selected) return "cyan";
  if (riskState === "CRITICAL" || riskState === "WARNING") return "orange";
  return "none";
}

function riskBadgeType(riskState: string): "execute" | "hold" | "no-trade" {
  if (riskState === "CRITICAL") return "no-trade";
  if (riskState === "WARNING") return "hold";
  return "execute";
}

export function AccountCard({ account, selected, onClick }: AccountCardProps) {
  const equityPulse = useLivePulse(account.equity);
  const balancePulse = useLivePulse(account.balance);
  const pulse = equityPulse || balancePulse;

  return (
    <Panel
      glow={accountGlow(account.risk_state ?? "", selected)}
      className={`cursor-pointer transition-all duration-200${pulse ? " live-pulse" : ""}`}
      onClick={onClick}
    >
      {/* Header row */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 12,
        }}
      >
        <div>
          <div
            style={{
              fontSize: 13,
              fontWeight: 700,
              color: "var(--text-primary)",
            }}
          >
            {account.account_name}
          </div>
          <div
            style={{
              fontSize: 10,
              color: "var(--text-muted)",
              marginTop: 2,
            }}
          >
            {account.broker} · {account.currency}
          </div>
        </div>

        <StatusBadge
          type={riskBadgeType(account.risk_state ?? "")}
          label={account.risk_state ?? "OK"}
        />
      </div>

      {/* Stats grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, 1fr)",
          gap: 10,
        }}
      >
        <Stat label="BALANCE" value={`$${formatNumber(account.balance)}`} />
        <Stat label="EQUITY" value={`$${formatNumber(account.equity)}`} />
        <Stat
          label="DAILY DD"
          value={`${account.daily_dd_percent?.toFixed(2)}%`}
          color={account.daily_dd_percent > 3 ? "var(--red)" : undefined}
        />
        <Stat
          label="OPEN TRADES"
          value={`${account.open_trades}/${account.max_concurrent_trades}`}
        />
      </div>

      {/* Prop firm indicator */}
      {account.prop_firm && (
        <div className="mt-3 text-center">
          <StatusBadge
            type="execute"
            label={`PROP FIRM${account.prop_firm_code ? ` — ${account.prop_firm_code}` : ""}`}
          />
        </div>
      )}
    </Panel>
  );
}

function Stat({
  label,
  value,
  color = "var(--text-primary)",
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div>
      <div
        style={{
          fontSize: 9,
          color: "var(--text-muted)",
          letterSpacing: "0.08em",
          marginBottom: 2,
        }}
      >
        {label}
      </div>
      <div
        className="num"
        style={{ fontSize: 14, fontWeight: 600, color }}
      >
        {value}
      </div>
    </div>
  );
}

// ─── CREATE ACCOUNT FORM ──────────────────────────────────────

