"use client";

// ============================================================
// TUYUL FX Wolf-15 — Account Detail Drawer
// Slide-out panel showing full account details + eligibility.
// ============================================================

import { useState, useEffect } from "react";
import type { Account } from "@/types";
import { usePropFirmStatus, usePropFirmPhase, archiveAccount } from "@/lib/api";
import Panel from "@/components/ui/Panel";
import AccountReadinessBadge from "@/components/AccountReadinessBadge";
import AccountEligibilityPanel from "@/components/AccountEligibilityPanel";
import { formatNumber } from "@/lib/formatters";

interface AccountDetailDrawerProps {
    account: Account;
    onClose: () => void;
}

function DetailRow({ label, value, color }: { label: string; value: string; color?: string }) {
    return (
        <div style={{ display: "flex", justifyContent: "space-between", padding: "4px 0" }}>
            <span style={{ fontSize: 10, color: "var(--text-muted)", letterSpacing: "0.06em" }}>{label}</span>
            <span className="num" style={{ fontSize: 11, fontWeight: 600, color: color ?? "var(--text-primary)" }}>
                {value}
            </span>
        </div>
    );
}

export default function AccountDetailDrawer({ account, onClose }: AccountDetailDrawerProps) {
    const { data: propStatus } = usePropFirmStatus(account.prop_firm ? account.account_id : "");
    const { data: propPhase } = usePropFirmPhase(account.prop_firm ? account.account_id : "");
    const [archiving, setArchiving] = useState(false);
    const [archived, setArchived] = useState(false);

    const handleArchive = async () => {
        if (!window.confirm("Archive this account? This cannot be undone.")) return;
        setArchiving(true);
        try {
            await archiveAccount(account.account_id, "ACCOUNT_ARCHIVE_FROM_UI");
            setArchived(true);
            setTimeout(() => {
                onClose();
                window.location.reload(); // Or trigger refresh via SWR/React Query if available
            }, 800);
        } catch (err) {
            alert("Failed to archive account");
        } finally {
            setArchiving(false);
        }
    };

    if (archived) {
        return (
            <div style={{ padding: 40, textAlign: "center" }}>
                <div style={{ fontSize: 16, fontWeight: 700, color: "var(--green)", marginBottom: 12 }}>Account archived</div>
                <button className="btn btn-primary" onClick={onClose}>Close</button>
            </div>
        );
    }

    return (
        <div
            role="dialog"
            aria-modal="true"
            aria-label="Account details"
            style={{
                position: "fixed",
                inset: 0,
                background: "var(--bg-overlay, rgba(0,0,0,0.6))",
                display: "flex",
                justifyContent: "flex-end",
                zIndex: 100,
                backdropFilter: "blur(4px)",
            }}
            onClick={onClose}
        >
            <div
                className="animate-fade-in"
                style={{
                    width: 420,
                    maxWidth: "90vw",
                    height: "100vh",
                    overflowY: "auto",
                    background: "var(--bg-base)",
                    borderLeft: "1px solid var(--bg-border)",
                    padding: 24,
                    display: "flex",
                    flexDirection: "column",
                    gap: 16,
                }}
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header + Archive */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                    <div>
                        <h2 style={{ fontSize: 16, fontWeight: 800, color: "var(--text-primary)", margin: 0 }}>
                            {account.account_name}
                        </h2>
                        <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>
                            {account.account_id} · {account.broker} · {account.currency}
                        </div>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
                        <button
                            onClick={onClose}
                            className="btn btn-ghost"
                            style={{ fontSize: 16, padding: "4px 8px", lineHeight: 1 }}
                            aria-label="Close drawer"
                        >
                            ✕
                        </button>
                        {!account.is_archived && (
                            <button
                                className="btn btn-danger"
                                style={{ fontSize: 11, marginTop: 8, minWidth: 90 }}
                                onClick={handleArchive}
                                disabled={archiving}
                            >
                                {archiving ? "Archiving..." : "Archive"}
                            </button>
                        )}
                    </div>
                </div>

            {/* Readiness */}
            {account.readiness_score != null && (
                <Panel>
                    <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.12em", color: "var(--text-muted)", marginBottom: 8 }}>
                        READINESS
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                        <AccountReadinessBadge score={account.readiness_score} size="md" />
                        {account.usable_capital != null && (
                            <div>
                                <div style={{ fontSize: 9, color: "var(--text-muted)", letterSpacing: "0.06em" }}>USABLE CAPITAL</div>
                                <div className="num" style={{ fontSize: 16, fontWeight: 700, color: "var(--green)" }}>
                                    ${formatNumber(account.usable_capital)}
                                </div>
                            </div>
                        )}
                    </div>
                </Panel>
            )}

            {/* Account data source */}
            <Panel>
                <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.12em", color: "var(--text-muted)", marginBottom: 8 }}>
                    ACCOUNT TYPE
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span
                        style={{
                            padding: "2px 8px",
                            borderRadius: 9999,
                            fontSize: 10,
                            fontWeight: 700,
                            background: account.data_source === "EA" ? "rgba(26, 110, 255, 0.12)" : "rgba(70, 95, 120, 0.08)",
                            color: account.data_source === "EA" ? "var(--blue)" : "var(--text-muted)",
                            border: `1px solid ${account.data_source === "EA" ? "rgba(26, 110, 255, 0.19)" : "rgba(70, 95, 120, 0.12)"}`,
                        }}
                    >
                        {account.data_source === "EA" ? "EA-LINKED" : "MANUAL"}
                    </span>
                    {account.prop_firm && (
                        <span
                            style={{
                                padding: "2px 8px",
                                borderRadius: 9999,
                                fontSize: 10,
                                fontWeight: 700,
                                background: "rgba(26, 110, 255, 0.08)",
                                color: "var(--accent, var(--yellow))",
                                border: "1px solid rgba(26, 110, 255, 0.15)",
                            }}
                        >
                            PROP FIRM — {account.prop_firm_code?.toUpperCase()}
                        </span>
                    )}
                </div>
            </Panel>

            {/* Financial details */}
            <Panel>
                <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.12em", color: "var(--text-muted)", marginBottom: 8 }}>
                    FINANCIALS
                </div>
                <DetailRow label="BALANCE" value={`$${formatNumber(account.balance)}`} />
                <DetailRow
                    label="EQUITY"
                    value={`$${formatNumber(account.equity)}`}
                    color={account.equity >= account.balance ? "var(--green)" : "var(--red)"}
                />
                <DetailRow label="EQUITY HIGH" value={`$${formatNumber(account.equity_high)}`} />
                <DetailRow
                    label="DAILY DD"
                    value={`${account.daily_dd_percent?.toFixed(2)}%`}
                    color={account.daily_dd_percent > 3 ? "var(--red)" : undefined}
                />
                <DetailRow
                    label="TOTAL DD"
                    value={`${account.total_dd_percent?.toFixed(2)}%`}
                    color={account.total_dd_percent > 5 ? "var(--red)" : undefined}
                />
                <DetailRow
                    label="OPEN TRADES"
                    value={`${account.open_trades}/${account.max_concurrent_trades}`}
                />
                <DetailRow label="OPEN RISK" value={`${account.open_risk_percent?.toFixed(2)}%`} />
            </Panel>

            {/* Prop firm status */}
            {account.prop_firm && propStatus && (
                <Panel>
                    <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.12em", color: "var(--text-muted)", marginBottom: 8 }}>
                        PROP FIRM STATUS
                    </div>
                    <DetailRow label="CODE" value={propStatus.code} />
                    <DetailRow
                        label="ALLOWED"
                        value={propStatus.allowed ? "YES" : "NO"}
                        color={propStatus.allowed ? "var(--green)" : "var(--red)"}
                    />
                    {propStatus.details && <DetailRow label="DETAILS" value={propStatus.details} />}
                </Panel>
            )}

            {/* Prop firm phase */}
            {account.prop_firm && propPhase && (
                <Panel>
                    <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.12em", color: "var(--text-muted)", marginBottom: 8 }}>
                        PROP FIRM PHASE
                    </div>
                    <DetailRow label="PHASE" value={propPhase.phase_name} />
                    {propPhase.progress_percent != null && (
                        <>
                            <DetailRow label="PROGRESS" value={`${propPhase.progress_percent}%`} />
                            <div
                                style={{
                                    height: 4,
                                    borderRadius: 2,
                                    background: "var(--bg-border)",
                                    marginTop: 4,
                                    overflow: "hidden",
                                }}
                            >
                                <div
                                    style={{
                                        width: `${Math.min(100, propPhase.progress_percent)}%`,
                                        height: "100%",
                                        background: "var(--green)",
                                        borderRadius: 2,
                                        transition: "width 0.3s ease",
                                    }}
                                />
                            </div>
                        </>
                    )}
                </Panel>
            )}

            {/* Eligibility panel */}
            {account.eligibility_flags && (
                <Panel>
                    <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.12em", color: "var(--text-muted)", marginBottom: 8 }}>
                        ELIGIBILITY
                    </div>
                    <AccountEligibilityPanel
                        flags={account.eligibility_flags}
                        lockReasons={account.lock_reasons ?? []}
                    />
                </Panel>
            )}
        </div>
    </div>
);
}
