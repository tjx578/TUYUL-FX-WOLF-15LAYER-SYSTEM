"use client";

import type { TakeSignalAccountOption } from "../api/signalActions.api";

interface Props {
    accounts: TakeSignalAccountOption[];
    selectedAccountId: string | null;
    onSelect: (accountId: string) => void;
    disabled?: boolean;
}

function statusColor(state?: string): string {
    switch (state) {
        case "SAFE":
            return "var(--green)";
        case "WARNING":
            return "var(--yellow)";
        case "CRITICAL":
            return "var(--red)";
        default:
            return "var(--text-muted)";
    }
}

export function EligibleAccountsPanel({
    accounts,
    selectedAccountId,
    onSelect,
    disabled = false,
}: Props) {
    if (accounts.length === 0) {
        return (
            <div
                style={{
                    padding: 12,
                    borderRadius: 10,
                    border: "1px dashed rgba(255,255,255,0.16)",
                    opacity: 0.8,
                }}
            >
                No accounts available for signal routing.
            </div>
        );
    }

    return (
        <div style={{ display: "grid", gap: 10 }}>
            {accounts.map((account) => {
                const selected = selectedAccountId === account.accountId;
                const selectable = account.selectable !== false && !!account.eaInstanceId;

                return (
                    <button
                        key={account.accountId}
                        type="button"
                        disabled={disabled || !selectable}
                        onClick={() => onSelect(account.accountId)}
                        style={{
                            textAlign: "left",
                            padding: 12,
                            borderRadius: 10,
                            border: selected
                                ? "1px solid var(--accent)"
                                : "1px solid rgba(255,255,255,0.12)",
                            background: selected ? "rgba(0,229,255,0.06)" : "transparent",
                            color: "inherit",
                            cursor: disabled || !selectable ? "not-allowed" : "pointer",
                            opacity: disabled || !selectable ? 0.65 : 1,
                        }}
                    >
                        <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                            <strong>{account.accountName}</strong>
                            <span
                                style={{
                                    fontSize: 12,
                                    fontWeight: 700,
                                    color: statusColor(account.riskState),
                                }}
                            >
                                {account.riskState ?? "UNKNOWN"}
                            </span>
                        </div>

                        <div style={{ fontSize: 12, opacity: 0.8, marginTop: 6 }}>
                            {account.broker} • {account.currency}
                            {account.propFirmCode ? ` • ${account.propFirmCode}` : ""}
                        </div>

                        <div style={{ fontSize: 12, opacity: 0.85, marginTop: 6 }}>
                            Balance: {account.balance.toFixed(2)} • Equity: {account.equity.toFixed(2)}
                        </div>

                        <div style={{ fontSize: 12, opacity: 0.85, marginTop: 4 }}>
                            DD: {account.dailyDdPercent ?? 0}% daily • {account.totalDdPercent ?? 0}% total
                        </div>

                        <div style={{ fontSize: 12, opacity: 0.85, marginTop: 4 }}>
                            Open: {account.openTrades ?? 0}/{account.maxConcurrentTrades ?? 0}
                        </div>

                        {!account.eaInstanceId && (
                            <div style={{ fontSize: 12, color: "var(--red)", marginTop: 8 }}>
                                Missing EA instance binding
                            </div>
                        )}

                        {account.eligibilityReason && (
                            <div
                                style={{
                                    fontSize: 12,
                                    color: selectable ? "var(--text-muted)" : "var(--red)",
                                    marginTop: 8,
                                }}
                            >
                                {account.eligibilityReason}
                            </div>
                        )}
                    </button>
                );
            })}
        </div>
    );
}
