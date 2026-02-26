"use client";

// ============================================================
// TUYUL FX Wolf-15 — Account Panel Components
// Exports: AccountCard, CreateAccountForm
// Used by: /accounts page
// ============================================================

import { useState } from "react";
import type { Account, AccountCreate } from "@/types";
import { createAccount } from "@/lib/api";

// ─── ACCOUNT CARD ─────────────────────────────────────────────

interface AccountCardProps {
  account: Account;
  selected: boolean;
  onClick: () => void;
}

export function AccountCard({ account, selected, onClick }: AccountCardProps) {
  const riskColor =
    account.risk_state === "CRITICAL"
      ? "var(--red)"
      : account.risk_state === "WARNING"
      ? "var(--yellow)"
      : "var(--green)";

  return (
    <div
      className="card"
      onClick={onClick}
      style={{
        cursor: "pointer",
        borderColor: selected ? "var(--accent)" : undefined,
        boxShadow: selected ? "0 0 0 1px var(--accent)" : undefined,
        transition: "border-color 0.2s, box-shadow 0.2s",
      }}
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

        <span
          className="badge"
          style={{
            fontSize: 9,
            background: `${riskColor}1a`,
            color: riskColor,
            borderColor: `${riskColor}40`,
          }}
        >
          {account.risk_state}
        </span>
      </div>

      {/* Stats grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, 1fr)",
          gap: 10,
        }}
      >
        <Stat label="BALANCE" value={`$${account.balance?.toLocaleString()}`} />
        <Stat label="EQUITY" value={`$${account.equity?.toLocaleString()}`} />
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
        <div
          style={{
            marginTop: 10,
            padding: "4px 8px",
            background: "var(--accent-dim)",
            borderRadius: 4,
            fontSize: 10,
            color: "var(--accent)",
            fontWeight: 600,
            letterSpacing: "0.06em",
            textAlign: "center",
          }}
        >
          PROP FIRM {account.prop_firm_code ? `— ${account.prop_firm_code}` : ""}
        </div>
      )}
    </div>
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

interface CreateAccountFormProps {
  onCreated: () => void;
  onCancel: () => void;
}

export function CreateAccountForm({ onCreated, onCancel }: CreateAccountFormProps) {
  const [form, setForm] = useState<AccountCreate>({
    broker: "",
    account_name: "",
    balance: 0,
    equity: 0,
    currency: "USD",
  });
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.broker || !form.account_name || form.balance <= 0) {
      setError("Please fill all required fields");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await createAccount(form);
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create account");
    } finally {
      setSubmitting(false);
    }
  };

  const inputStyle: React.CSSProperties = {
    width: "100%",
    padding: "8px 10px",
    fontSize: 12,
    background: "var(--bg-base)",
    border: "1px solid var(--bg-border)",
    borderRadius: 4,
    color: "var(--text-primary)",
    outline: "none",
  };

  const labelStyle: React.CSSProperties = {
    fontSize: 10,
    fontWeight: 600,
    color: "var(--text-muted)",
    letterSpacing: "0.06em",
    marginBottom: 4,
    display: "block",
  };

  return (
    <div
      className="card"
      style={{
        width: 380,
        padding: 24,
        display: "flex",
        flexDirection: "column",
        gap: 16,
      }}
    >
      <div
        style={{
          fontSize: 13,
          fontWeight: 700,
          color: "var(--text-primary)",
          letterSpacing: "0.04em",
        }}
      >
        CREATE ACCOUNT
      </div>

      <form
        onSubmit={handleSubmit}
        style={{ display: "flex", flexDirection: "column", gap: 12 }}
      >
        <div>
          <label style={labelStyle}>ACCOUNT NAME *</label>
          <input
            style={inputStyle}
            value={form.account_name}
            onChange={(e) =>
              setForm({ ...form, account_name: e.target.value })
            }
            placeholder="My Trading Account"
          />
        </div>

        <div>
          <label style={labelStyle}>BROKER *</label>
          <input
            style={inputStyle}
            value={form.broker}
            onChange={(e) => setForm({ ...form, broker: e.target.value })}
            placeholder="IC Markets"
          />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div>
            <label style={labelStyle}>BALANCE *</label>
            <input
              style={inputStyle}
              type="number"
              value={form.balance || ""}
              onChange={(e) =>
                setForm({ ...form, balance: parseFloat(e.target.value) || 0 })
              }
              placeholder="10000"
            />
          </div>
          <div>
            <label style={labelStyle}>CURRENCY</label>
            <select
              style={inputStyle}
              value={form.currency}
              onChange={(e) => setForm({ ...form, currency: e.target.value })}
            >
              <option value="USD">USD</option>
              <option value="EUR">EUR</option>
              <option value="GBP">GBP</option>
            </select>
          </div>
        </div>

        <div>
          <label style={labelStyle}>PROP FIRM CODE (optional)</label>
          <input
            style={inputStyle}
            value={form.prop_firm_code ?? ""}
            onChange={(e) =>
              setForm({
                ...form,
                prop_firm_code: e.target.value || undefined,
              })
            }
            placeholder="FTMO / MFF / TFT"
          />
        </div>

        {error && (
          <div style={{ fontSize: 11, color: "var(--red)", padding: "4px 0" }}>
            {error}
          </div>
        )}

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button
            type="button"
            className="btn btn-ghost"
            style={{ fontSize: 11 }}
            onClick={onCancel}
          >
            CANCEL
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            style={{ fontSize: 11 }}
            disabled={submitting}
          >
            {submitting ? "CREATING..." : "CREATE"}
          </button>
        </div>
      </form>
    </div>
  );
}
