"use client";

import { useState } from "react";
import type { Status, Dimension } from "./_audit-data";
import { STATUS_META, DIMENSIONS } from "./_audit-data";

// ── Helper components ─────────────────────────────────────────

function StatusBadge({ status }: { status: Status }) {
    const m = STATUS_META[status];
    return (
        <span
            style={{
                display: "inline-flex",
                alignItems: "center",
                padding: "2px 8px",
                borderRadius: "var(--radius-sm)",
                background: m.bg,
                border: `1px solid ${m.border}`,
                color: m.color,
                fontFamily: "var(--font-mono)",
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: "0.08em",
                whiteSpace: "nowrap",
            }}
        >
            {m.label}
        </span>
    );
}

function ScoreBar({ value, max = 10, color }: { value: number; max?: number; color: string }) {
    const pct = (value / max) * 100;
    return (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div
                style={{
                    flex: 1,
                    height: 4,
                    background: "var(--bg-elevated)",
                    borderRadius: 2,
                    overflow: "hidden",
                }}
            >
                <div
                    style={{
                        width: `${pct}%`,
                        height: "100%",
                        background: color,
                        borderRadius: 2,
                        transition: "width 0.4s ease",
                    }}
                />
            </div>
            <span
                style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 11,
                    fontWeight: 700,
                    color,
                    minWidth: 36,
                    textAlign: "right",
                }}
            >
                {value}
            </span>
        </div>
    );
}

// ── Interactive explorer (client component) ───────────────────

function dimCounts(d: Dimension) {
    return {
        VERIFIED: d.items.filter((i) => i.status === "VERIFIED").length,
        PARTIAL: d.items.filter((i) => i.status === "PARTIAL").length,
        GAP: d.items.filter((i) => i.status === "GAP").length,
        EXCEEDS: d.items.filter((i) => i.status === "EXCEEDS").length,
    };
}

export function AuditExplorer() {
    const [activeDim, setActiveDim] = useState<string>("websocket");
    const [expandedItem, setExpandedItem] = useState<number | null>(null);

    const dim = DIMENSIONS.find((d) => d.id === activeDim)!;

    return (
        <div style={{ display: "grid", gridTemplateColumns: "240px 1fr", gap: 14 }}>

            {/* ── Left: dimension list ── */}
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {DIMENSIONS.map((d) => {
                    const c = dimCounts(d);
                    const isActive = activeDim === d.id;
                    const scoreColor = d.pdfScore >= 9.5 ? "var(--green)" : d.pdfScore >= 8.5 ? "var(--cyan)" : d.pdfScore >= 8.0 ? "var(--yellow)" : "var(--red)";
                    return (
                        <button
                            key={d.id}
                            onClick={() => { setActiveDim(d.id); setExpandedItem(null); }}
                            aria-selected={isActive}
                            style={{
                                padding: "10px 12px",
                                borderRadius: "var(--radius-md)",
                                border: `1px solid ${isActive ? "var(--accent)" : "var(--border-default)"}`,
                                background: isActive ? "var(--accent-muted)" : "var(--bg-card)",
                                cursor: "pointer",
                                textAlign: "left",
                                display: "flex",
                                flexDirection: "column",
                                gap: 6,
                            }}
                        >
                            <div style={{ fontSize: 11, fontWeight: isActive ? 700 : 500, color: isActive ? "var(--accent)" : "var(--text-secondary)" }}>
                                {d.label}
                            </div>
                            <ScoreBar value={d.pdfScore} color={scoreColor} />
                            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                                {c.VERIFIED > 0 && (
                                    <span style={{ fontSize: 8, color: "var(--green)", fontFamily: "var(--font-mono)" }}>
                                        {c.VERIFIED}V
                                    </span>
                                )}
                                {c.EXCEEDS > 0 && (
                                    <span style={{ fontSize: 8, color: "var(--cyan)", fontFamily: "var(--font-mono)" }}>
                                        {c.EXCEEDS}E
                                    </span>
                                )}
                                {c.PARTIAL > 0 && (
                                    <span style={{ fontSize: 8, color: "var(--yellow)", fontFamily: "var(--font-mono)" }}>
                                        {c.PARTIAL}P
                                    </span>
                                )}
                                {c.GAP > 0 && (
                                    <span style={{ fontSize: 8, color: "var(--red)", fontFamily: "var(--font-mono)" }}>
                                        {c.GAP}G
                                    </span>
                                )}
                            </div>
                        </button>
                    );
                })}

                {/* ── Score comparison ── */}
                <div
                    className="card"
                    style={{ padding: "12px 14px", marginTop: 8, display: "flex", flexDirection: "column", gap: 8 }}
                >
                    <div style={{ fontSize: 9, fontWeight: 700, color: "var(--text-muted)", letterSpacing: "0.08em", fontFamily: "var(--font-mono)" }}>
                        OVERALL SCORES
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                        <div>
                            <div style={{ fontSize: 9, color: "var(--text-muted)", marginBottom: 3 }}>PDF Claim</div>
                            <ScoreBar value={8.75} color="var(--accent)" />
                        </div>
                        <div>
                            <div style={{ fontSize: 9, color: "var(--text-muted)", marginBottom: 3 }}>Institutional Grade</div>
                            <ScoreBar value={9.25} color="var(--cyan)" />
                        </div>
                    </div>
                </div>
            </div>

            {/* ── Right: dimension detail ── */}
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>

                {/* Dimension header */}
                <div
                    className="card"
                    style={{ padding: "14px 18px", display: "flex", alignItems: "center", gap: 16 }}
                >
                    <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 16, fontWeight: 800, color: "var(--text-primary)", fontFamily: "var(--font-display)", letterSpacing: "0.04em" }}>
                            {dim.label.toUpperCase()}
                        </div>
                        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                            {dim.items.length} claims verified against actual repo files
                        </div>
                    </div>
                    <div style={{ display: "flex", gap: 16 }}>
                        <div style={{ textAlign: "center" }}>
                            <div style={{ fontSize: 9, color: "var(--text-muted)", fontFamily: "var(--font-mono)", letterSpacing: "0.06em" }}>PDF SCORE</div>
                            <div style={{ fontSize: 22, fontWeight: 900, color: "var(--accent)", fontFamily: "var(--font-display)" }}>
                                {dim.pdfScore}
                            </div>
                        </div>
                        <div style={{ textAlign: "center" }}>
                            <div style={{ fontSize: 9, color: "var(--text-muted)", fontFamily: "var(--font-mono)", letterSpacing: "0.06em" }}>INST. GRADE</div>
                            <div style={{ fontSize: 22, fontWeight: 900, color: "var(--cyan)", fontFamily: "var(--font-display)" }}>
                                {dim.institutionalGrade}
                            </div>
                        </div>
                    </div>
                </div>

                {/* Claim items */}
                {dim.items.map((item, idx) => {
                    const m = STATUS_META[item.status];
                    const isOpen = expandedItem === idx;
                    return (
                        <div
                            key={idx}
                            className="card"
                            style={{
                                padding: 0,
                                overflow: "hidden",
                                borderColor: isOpen ? m.border : "var(--border-default)",
                                transition: "border-color 0.15s",
                            }}
                        >
                            {/* Header row */}
                            <button
                                onClick={() => setExpandedItem(isOpen ? null : idx)}
                                style={{
                                    width: "100%",
                                    padding: "12px 16px",
                                    background: isOpen ? m.bg : "transparent",
                                    border: "none",
                                    cursor: "pointer",
                                    textAlign: "left",
                                    display: "flex",
                                    alignItems: "flex-start",
                                    gap: 12,
                                    transition: "background 0.15s",
                                }}
                            >
                                <StatusBadge status={item.status} />
                                <div style={{ flex: 1, fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.5 }}>
                                    {item.claim}
                                </div>
                                <span
                                    style={{
                                        fontSize: 10,
                                        color: "var(--text-faint)",
                                        flexShrink: 0,
                                        fontFamily: "var(--font-mono)",
                                        marginTop: 1,
                                    }}
                                >
                                    {isOpen ? "▲" : "▼"}
                                </span>
                            </button>

                            {/* Expanded detail */}
                            {isOpen && (
                                <div
                                    style={{
                                        padding: "0 16px 14px",
                                        display: "flex",
                                        flexDirection: "column",
                                        gap: 8,
                                        borderTop: `1px solid ${m.border}`,
                                    }}
                                >
                                    <div style={{ paddingTop: 10 }}>
                                        <div
                                            style={{
                                                fontSize: 9,
                                                fontWeight: 700,
                                                color: "var(--text-muted)",
                                                letterSpacing: "0.08em",
                                                fontFamily: "var(--font-mono)",
                                                marginBottom: 6,
                                            }}
                                        >
                                            ACTUAL REPO STATE
                                        </div>
                                        <p
                                            style={{
                                                fontSize: 12,
                                                color: "var(--text-primary)",
                                                lineHeight: 1.6,
                                                margin: 0,
                                            }}
                                        >
                                            {item.actual}
                                        </p>
                                    </div>
                                    {item.file && (
                                        <div
                                            style={{
                                                display: "inline-flex",
                                                alignItems: "center",
                                                gap: 6,
                                                padding: "4px 10px",
                                                background: "var(--bg-elevated)",
                                                borderRadius: "var(--radius-sm)",
                                                border: "1px solid var(--border-default)",
                                                alignSelf: "flex-start",
                                            }}
                                        >
                                            <span style={{ fontSize: 9, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>FILE</span>
                                            <span style={{ fontSize: 10, color: "var(--accent)", fontFamily: "var(--font-mono)", fontWeight: 600 }}>
                                                {item.file}
                                            </span>
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>
        </div>
    );
}
