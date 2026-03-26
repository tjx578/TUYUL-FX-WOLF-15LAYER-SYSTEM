"use client";

import { IMPACT_STYLES, IMPACT_FILTERS, CURRENCY_OPTIONS } from "../model/news.types";

interface NewsFilterBarProps {
    period: "today" | "upcoming";
    setPeriod: (p: "today" | "upcoming") => void;
    impactFilter: string;
    setImpactFilter: (f: string) => void;
    currencyFilter: string;
    setCurrencyFilter: (c: string) => void;
    highCount: number;
    mediumCount: number;
    totalCount: number;
}

export function NewsFilterBar({
    period,
    setPeriod,
    impactFilter,
    setImpactFilter,
    currencyFilter,
    setCurrencyFilter,
    highCount,
    mediumCount,
    totalCount,
}: NewsFilterBarProps) {
    return (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
            {/* Period tabs */}
            <div style={{ display: "flex", gap: 4 }}>
                {(["today", "upcoming"] as const).map((p) => (
                    <button
                        key={p}
                        className="btn btn-ghost"
                        style={{
                            fontSize: 10,
                            padding: "5px 13px",
                            borderColor: period === p ? "var(--accent)" : "var(--border-default)",
                            color: period === p ? "var(--accent)" : "var(--text-muted)",
                            background: period === p ? "var(--accent-muted)" : "transparent",
                        }}
                        onClick={() => setPeriod(p)}
                        aria-pressed={period === p}
                    >
                        {p.toUpperCase()}
                    </button>
                ))}
            </div>

            {/* Impact filter */}
            <div style={{ display: "flex", gap: 4 }}>
                {IMPACT_FILTERS.map((f) => (
                    <button
                        key={f}
                        className="btn btn-ghost"
                        style={{
                            fontSize: 10,
                            padding: "5px 11px",
                            borderColor: impactFilter === f ? (IMPACT_STYLES[f as keyof typeof IMPACT_STYLES]?.color ?? "var(--border-strong)") : "var(--border-default)",
                            color: impactFilter === f ? (IMPACT_STYLES[f as keyof typeof IMPACT_STYLES]?.color ?? "var(--text-primary)") : "var(--text-muted)",
                        }}
                        onClick={() => setImpactFilter(f)}
                        aria-pressed={impactFilter === f}
                    >
                        {f}
                    </button>
                ))}
            </div>

            {/* Currency filter */}
            <select
                name="currency_filter"
                value={currencyFilter}
                onChange={(e) => setCurrencyFilter(e.target.value)}
                style={{ fontSize: 11, padding: "5px 10px" }}
                aria-label="Filter by currency"
            >
                {CURRENCY_OPTIONS.map((c) => (
                    <option key={c} value={c}>{c}</option>
                ))}
            </select>

            {/* Event count badges */}
            <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
                {highCount > 0 && (
                    <span className="badge badge-red">{highCount} HIGH</span>
                )}
                {mediumCount > 0 && (
                    <span className="badge badge-yellow">{mediumCount} MED</span>
                )}
                <span className="badge badge-muted">{totalCount} total</span>
            </div>
        </div>
    );
}
