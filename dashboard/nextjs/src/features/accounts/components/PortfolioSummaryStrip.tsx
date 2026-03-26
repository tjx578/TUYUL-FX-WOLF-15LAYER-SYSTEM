"use client";

import type { Account } from "@/types";
import { formatNumber } from "@/lib/formatters";

function KpiCard({ label, value, color }: { label: string; value: string; color?: string }) {
    return (
        <div className="card" style={{ display: "flex", flexDirection: "column", gap: 4, padding: "12px 15px" }}>
            <div style={{ fontSize: 9, letterSpacing: "0.12em", color: "var(--text-muted)", fontWeight: 700, fontFamily: "var(--font-mono)" }}>
                {label}
            </div>
            <div className="num" style={{ fontSize: 18, fontWeight: 700, color: color ?? "var(--text-primary)" }}>
                {value}
            </div>
        </div>
    );
}

export function PortfolioSummaryStrip({
    accounts,
    totalUsable,
    avgReadiness,
}: {
    accounts: Account[];
    totalUsable: number;
    avgReadiness: number;
}) {
    const totalBalance = accounts.reduce((s, a) => s + (a.balance ?? 0), 0);
    const totalEquity = accounts.reduce((s, a) => s + (a.equity ?? 0), 0);
    const propCount = accounts.filter((a) => a.prop_firm).length;
    const eaCount = accounts.filter((a) => a.data_source === "EA").length;

    return (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 10 }}>
            <KpiCard label="TOTAL BALANCE" value={`$${formatNumber(totalBalance)}`} />
            <KpiCard
                label="TOTAL EQUITY"
                value={`$${formatNumber(totalEquity)}`}
                color={totalEquity >= totalBalance ? "var(--green)" : "var(--red)"}
            />
            <KpiCard
                label="USABLE CAPITAL"
                value={`$${formatNumber(totalUsable)}`}
                color="var(--green)"
            />
            <KpiCard
                label="AVG READINESS"
                value={`${Math.round(avgReadiness * 100)}%`}
                color={avgReadiness >= 0.7 ? "var(--green)" : avgReadiness >= 0.4 ? "var(--yellow)" : "var(--red)"}
            />
            <KpiCard label="ACCOUNTS" value={String(accounts.length)} color="var(--blue)" />
            <KpiCard
                label="PROP / EA"
                value={`${propCount} / ${eaCount}`}
                color={propCount > 0 ? "var(--accent, var(--yellow))" : "var(--text-muted)"}
            />
        </div>
    );
}
