"use client";

import React from "react";
import { useConfirmTradeMutation } from "@/hooks/mutations/useConfirmTradeMutation";
import { useCloseTradeMutation } from "@/hooks/mutations/useCloseTradeMutation";
import type { TradeDeskTrade } from "@/schema/tradeDeskSchema";

// ── TradeActionPanel ─────────────────────────────────────────

interface TradeActionPanelProps {
    trade: TradeDeskTrade;
}

export function TradeActionPanel({ trade }: TradeActionPanelProps) {
    const confirmMutation = useConfirmTradeMutation(trade.account_id, trade.trade_id);
    const closeMutation = useCloseTradeMutation(trade.account_id, trade.trade_id);

    const isPending = trade.status === "INTENDED" || trade.status === "PENDING";
    const isOpen = trade.status === "OPEN";
    const isTerminal = trade.status === "CLOSED" || trade.status === "CANCELLED" || trade.status === "SKIPPED";

    if (isTerminal) {
        return (
            <div style={{ fontSize: 10, color: "var(--text-muted)", fontFamily: "var(--font-mono)", padding: "8px 0" }}>
                Trade is in terminal state ({trade.status}). No actions available.
            </div>
        );
    }

    return (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {/* Confirm: only for INTENDED trades */}
            {trade.status === "INTENDED" && (
                <ActionButton
                    label="CONFIRM"
                    testId="confirm-trade-btn"
                    color="var(--green)"
                    bg="var(--green-glow)"
                    border="var(--border-success)"
                    loading={confirmMutation.isPending}
                    onClick={() => confirmMutation.mutate(undefined)}
                />
            )}

            {/* Close: for PENDING or OPEN trades */}
            {(isPending || isOpen) && (
                <ActionButton
                    label="CLOSE"
                    testId="close-trade-btn"
                    color="var(--red)"
                    bg="var(--red-glow, rgba(255,77,79,0.08))"
                    border="var(--border-danger)"
                    loading={closeMutation.isPending}
                    onClick={() => closeMutation.mutate(undefined)}
                />
            )}
        </div>
    );
}

// ── ActionButton ─────────────────────────────────────────────

function ActionButton({
    label,
    testId,
    color,
    bg,
    border,
    loading,
    onClick,
}: {
    label: string;
    testId?: string;
    color: string;
    bg: string;
    border: string;
    loading: boolean;
    onClick: () => void;
}) {
    return (
        <button
            onClick={onClick}
            disabled={loading}
            data-testid={testId}
            style={{
                padding: "6px 14px",
                fontSize: 10,
                fontWeight: 700,
                fontFamily: "var(--font-mono)",
                letterSpacing: "0.06em",
                background: bg,
                color,
                border: `1px solid ${border}`,
                borderRadius: "var(--radius-sm, 6px)",
                cursor: loading ? "wait" : "pointer",
                opacity: loading ? 0.6 : 1,
                transition: "opacity 0.15s ease",
            }}
        >
            {loading ? "..." : label}
        </button>
    );
}
