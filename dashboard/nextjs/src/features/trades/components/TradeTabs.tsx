"use client";

import React from "react";
import type { TradeTab } from "@/store/useTradeDeskStore";
import type { TradeDeskCounts } from "../model/tradeDeskSchema";

// ── TradeTabs ────────────────────────────────────────────────

interface TradeTabsProps {
    activeTab: TradeTab;
    onTabChange: (tab: TradeTab) => void;
    counts: TradeDeskCounts | null;
}

const TABS: { key: TradeTab; label: string; countKey: keyof TradeDeskCounts }[] = [
    { key: "pending", label: "PENDING", countKey: "pending" },
    { key: "open", label: "OPEN", countKey: "open" },
    { key: "closed", label: "CLOSED", countKey: "closed" },
    { key: "cancelled", label: "CANCELLED", countKey: "cancelled" },
];

export function TradeTabs({ activeTab, onTabChange, counts }: TradeTabsProps) {
    return (
        <div
            style={{
                display: "flex",
                gap: 2,
                background: "var(--bg-elevated)",
                borderRadius: "var(--radius-md, 8px)",
                padding: 3,
                border: "1px solid var(--border-subtle)",
            }}
        >
            {TABS.map((tab) => {
                const isActive = activeTab === tab.key;
                const count = counts?.[tab.countKey] ?? 0;
                return (
                    <button
                        key={tab.key}
                        data-testid={`trade-tab-${tab.key}`}
                        data-active={isActive ? "true" : "false"}
                        onClick={() => onTabChange(tab.key)}
                        style={{
                            flex: 1,
                            padding: "7px 12px",
                            background: isActive ? "var(--bg-surface)" : "transparent",
                            border: isActive ? "1px solid var(--border-default)" : "1px solid transparent",
                            borderRadius: "var(--radius-sm, 6px)",
                            color: isActive ? "var(--text-primary)" : "var(--text-muted)",
                            fontSize: 10,
                            fontWeight: 700,
                            fontFamily: "var(--font-mono)",
                            letterSpacing: "0.08em",
                            cursor: "pointer",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            gap: 6,
                            transition: "all 0.15s ease",
                        }}
                    >
                        {tab.label}
                        {count > 0 && (
                            <span
                                style={{
                                    fontSize: 9,
                                    padding: "1px 5px",
                                    borderRadius: 10,
                                    background: isActive ? "var(--blue-glow, rgba(56,189,248,0.12))" : "var(--bg-elevated)",
                                    color: isActive ? "var(--blue, #38bdf8)" : "var(--text-muted)",
                                    fontWeight: 800,
                                    minWidth: 18,
                                    textAlign: "center",
                                }}
                            >
                                {count}
                            </span>
                        )}
                    </button>
                );
            })}
        </div>
    );
}
