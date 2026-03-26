"use client";

import type { Account } from "@/types";
import { formatNumber } from "@/lib/formatters";
import AccountReadinessBadge from "./AccountReadinessBadge";

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
            <div style={{ fontSize: 9, color: "var(--text-muted)", letterSpacing: "0.08em", marginBottom: 2 }}>
                {label}
            </div>
            <div className="num" style={{ fontSize: 13, fontWeight: 600, color }}>
                {value}
            </div>
        </div>
    );
}

export function AccountGridCard({
    account,
    riskSnap,
    onClick,
    highlighted = false,
}: {
    account: Account;
    riskSnap?: { status: string; circuit_breaker: boolean };
    onClick: () => void;
    highlighted?: boolean;
}) {
    const readiness = account.readiness_score ?? 0;
    const usable = account.usable_capital ?? 0;

    return (
        <div
            role="listitem"
            tabIndex={0}
            className="card cursor-pointer transition-all duration-200 hover:border-[var(--blue)]"
            style={{
                padding: 16,
                display: "flex",
                flexDirection: "column",
                gap: 10,
                border: highlighted
                    ? "1px solid var(--accent)"
                    : undefined,
                background: highlighted
                    ? "rgba(0,229,255,0.06)"
                    : undefined,
            }}
            onClick={onClick}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(); } }}
            aria-label={`Account ${account.account_name}, ${account.broker}, balance $${formatNumber(account.balance)}`}
        >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>
                        {account.account_name}
                    </div>
                    <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2, display: "flex", gap: 6, alignItems: "center" }}>
                        <span>{account.broker}</span>
                        <span>·</span>
                        <span>{account.currency}</span>
                        {account.data_source === "EA" && (
                            <span
                                style={{
                                    fontSize: 8,
                                    fontWeight: 700,
                                    padding: "1px 4px",
                                    borderRadius: 3,
                                    background: "rgba(26, 110, 255, 0.08)",
                                    color: "var(--blue)",
                                }}
                            >
                                EA
                            </span>
                        )}
                    </div>
                </div>
                <AccountReadinessBadge score={readiness} />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 8 }}>
                <Stat label="BALANCE" value={`$${formatNumber(account.balance)}`} />
                <Stat label="EQUITY" value={`$${formatNumber(account.equity)}`} />
                <Stat label="USABLE CAPITAL" value={`$${formatNumber(usable)}`} color="var(--green)" />
                <Stat label="OPEN" value={`${account.open_trades}/${account.max_concurrent_trades}`} />
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                {account.prop_firm && (
                    <span
                        style={{
                            fontSize: 9,
                            fontWeight: 700,
                            padding: "2px 6px",
                            borderRadius: 9999,
                            background: "rgba(26, 110, 255, 0.07)",
                            color: "var(--accent, var(--yellow))",
                            border: "1px solid rgba(26, 110, 255, 0.12)",
                        }}
                    >
                        {account.prop_firm_code?.toUpperCase() ?? "PROP"}
                    </span>
                )}

                {riskSnap?.status === "CRITICAL" && (
                    <span
                        style={{
                            fontSize: 9,
                            fontWeight: 700,
                            padding: "2px 6px",
                            borderRadius: 9999,
                            background: "rgba(255, 61, 87, 0.07)",
                            color: "var(--red)",
                            border: "1px solid rgba(255, 61, 87, 0.12)",
                        }}
                    >
                        CRITICAL
                    </span>
                )}

                {riskSnap?.status === "WARNING" && (
                    <span
                        style={{
                            fontSize: 9,
                            fontWeight: 700,
                            padding: "2px 6px",
                            borderRadius: 9999,
                            background: "rgba(255, 215, 64, 0.07)",
                            color: "var(--yellow)",
                            border: "1px solid rgba(255, 215, 64, 0.12)",
                        }}
                    >
                        WARNING
                    </span>
                )}
            </div>
        </div>
    );
}
