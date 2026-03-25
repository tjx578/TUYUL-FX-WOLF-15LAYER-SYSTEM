"use client";

// ============================================================
// TUYUL FX Wolf-15 — SignalDetailPanel
// Full L12 verdict detail: direction, prices, gate analysis,
// scores breakdown, session info, expiration countdown.
// ============================================================

import type { L12Verdict } from "@/types";
import { GateStatus } from "@/components/GateStatus";
import StatusBadge from "@/components/ui/StatusBadge";
import { formatTime } from "@/lib/timezone";

interface SignalDetailPanelProps {
    verdict: L12Verdict;
    onClose: () => void;
}

function verdictBadgeType(v: string): "execute" | "hold" | "no-trade" | "abort" {
    if (v.startsWith("EXECUTE")) return "execute";
    if (v === "HOLD") return "hold";
    if (v === "ABORT") return "abort";
    return "no-trade";
}

function directionColor(d?: string): string {
    if (d === "BUY") return "var(--cyan)";
    if (d === "SELL") return "var(--red)";
    return "var(--text-muted)";
}

function expirationLabel(expiresAt?: number): { text: string; color: string } | null {
    if (!expiresAt) return null;
    const now = Math.floor(Date.now() / 1000);
    const diff = expiresAt - now;
    if (diff <= 0) return { text: "EXPIRED", color: "var(--red)" };
    const mins = Math.floor(diff / 60);
    const secs = diff % 60;
    if (mins > 60) {
        const hrs = Math.floor(mins / 60);
        return { text: `${hrs}h ${mins % 60}m`, color: "var(--green)" };
    }
    if (mins > 10) return { text: `${mins}m ${secs}s`, color: "var(--green)" };
    if (mins > 2) return { text: `${mins}m ${secs}s`, color: "var(--yellow)" };
    return { text: `${mins}m ${secs}s`, color: "var(--red)" };
}

function ScoreBar({ label, value, max, threshold }: { label: string; value: number; max: number; threshold: number }) {
    const pct = Math.min((value / max) * 100, 100);
    const passing = value >= threshold;

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10 }}>
                <span style={{ color: "var(--text-muted)", letterSpacing: "0.06em" }}>{label}</span>
                <span
                    className="num"
                    style={{ color: passing ? "var(--green)" : "var(--text-muted)", fontWeight: 700 }}
                >
                    {typeof value === "number" && max <= 1 ? value.toFixed(2) : value.toFixed(0)}/{max <= 1 ? max.toFixed(2) : max}
                </span>
            </div>
            <div
                style={{
                    height: 4,
                    borderRadius: 2,
                    background: "rgba(255,255,255,0.06)",
                    overflow: "hidden",
                    position: "relative",
                }}
            >
                {/* Threshold marker */}
                <div
                    style={{
                        position: "absolute",
                        left: `${(threshold / max) * 100}%`,
                        top: 0,
                        bottom: 0,
                        width: 1,
                        background: "rgba(255,255,255,0.2)",
                    }}
                />
                <div
                    style={{
                        height: "100%",
                        width: `${pct}%`,
                        borderRadius: 2,
                        background: passing ? "var(--green)" : "var(--yellow)",
                        transition: "width 0.3s ease",
                    }}
                />
            </div>
        </div>
    );
}

export function SignalDetailPanel({ verdict, onClose }: SignalDetailPanelProps) {
    const v = String(verdict.verdict ?? "");
    const isExecutable = v.startsWith("EXECUTE");
    const direction = verdict.direction ?? (v.includes("BUY") ? "BUY" : v.includes("SELL") ? "SELL" : undefined);
    const expiration = expirationLabel(verdict.expires_at);

    return (
        <div
            style={{
                display: "flex",
                flexDirection: "column",
                gap: 14,
                padding: "18px 18px",
                borderRadius: 12,
                background: "var(--bg-panel)",
                border: "1px solid var(--border-default)",
                position: "sticky",
                top: 24,
            }}
        >
            {/* ── Header ── */}
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span
                    style={{
                        fontSize: 18,
                        fontWeight: 800,
                        color: "var(--text-primary)",
                        fontFamily: "var(--font-mono)",
                        letterSpacing: "0.04em",
                    }}
                >
                    {verdict.symbol}
                </span>
                <StatusBadge type={verdictBadgeType(v)} label={v} />
                <button
                    onClick={onClose}
                    style={{
                        marginLeft: "auto",
                        background: "none",
                        border: "1px solid var(--border-default)",
                        color: "var(--text-muted)",
                        fontSize: 12,
                        padding: "3px 10px",
                        borderRadius: 6,
                        cursor: "pointer",
                        fontFamily: "var(--font-mono)",
                    }}
                    aria-label="Close detail panel"
                >
                    ✕
                </button>
            </div>

            {/* ── Direction + Expiration ── */}
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                {direction && (
                    <div
                        style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 6,
                            padding: "6px 14px",
                            borderRadius: 8,
                            background: direction === "BUY" ? "rgba(0,229,255,0.08)" : "rgba(255,61,87,0.08)",
                            border: `1px solid ${direction === "BUY" ? "rgba(0,229,255,0.25)" : "rgba(255,61,87,0.25)"}`,
                        }}
                    >
                        <span style={{ fontSize: 16 }}>{direction === "BUY" ? "▲" : "▼"}</span>
                        <span
                            style={{
                                fontSize: 13,
                                fontWeight: 800,
                                color: directionColor(direction),
                                letterSpacing: "0.08em",
                                fontFamily: "var(--font-mono)",
                            }}
                        >
                            {direction}
                        </span>
                    </div>
                )}

                {verdict.session && (
                    <span
                        className="badge badge-cyan"
                        style={{ fontSize: 9, letterSpacing: "0.08em" }}
                    >
                        {verdict.session}
                    </span>
                )}

                {expiration && (
                    <span
                        style={{
                            fontSize: 10,
                            fontFamily: "var(--font-mono)",
                            color: expiration.color,
                            fontWeight: 700,
                            letterSpacing: "0.04em",
                            marginLeft: "auto",
                        }}
                    >
                        ⏳ {expiration.text}
                    </span>
                )}
            </div>

            {/* ── Price Levels ── */}
            {isExecutable && (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    <div
                        style={{
                            fontSize: 9,
                            fontWeight: 700,
                            letterSpacing: "0.10em",
                            color: "var(--text-muted)",
                            fontFamily: "var(--font-mono)",
                        }}
                    >
                        PRICE LEVELS
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 6 }}>
                        {([
                            { label: "ENTRY", value: verdict.entry_price, color: "var(--text-primary)" },
                            { label: "STOP LOSS", value: verdict.stop_loss, color: "var(--red)" },
                            { label: "TP-1", value: verdict.take_profit_1, color: "var(--green)" },
                            { label: "TP-2", value: verdict.take_profit_2, color: "var(--green)" },
                        ] as const).map(({ label, value, color }) => (
                            <div
                                key={label}
                                style={{
                                    padding: "8px 10px",
                                    borderRadius: 6,
                                    background: "rgba(0,0,0,0.25)",
                                    border: "1px solid rgba(255,255,255,0.06)",
                                }}
                            >
                                <div
                                    style={{
                                        fontSize: 8,
                                        letterSpacing: "0.10em",
                                        color: "var(--text-muted)",
                                        marginBottom: 3,
                                        fontFamily: "var(--font-mono)",
                                    }}
                                >
                                    {label}
                                </div>
                                <div
                                    className="num"
                                    style={{ fontSize: 14, fontWeight: 700, color }}
                                >
                                    {value?.toFixed(5) ?? "—"}
                                </div>
                            </div>
                        ))}
                    </div>

                    {/* R:R */}
                    {verdict.risk_reward_ratio && (
                        <div
                            style={{
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "space-between",
                                padding: "8px 10px",
                                borderRadius: 6,
                                background: "rgba(0,0,0,0.25)",
                                border: "1px solid rgba(255,255,255,0.06)",
                            }}
                        >
                            <span
                                style={{
                                    fontSize: 9,
                                    letterSpacing: "0.10em",
                                    color: "var(--text-muted)",
                                    fontFamily: "var(--font-mono)",
                                }}
                            >
                                RISK : REWARD
                            </span>
                            <span
                                className="num"
                                style={{
                                    fontSize: 16,
                                    fontWeight: 800,
                                    color: verdict.risk_reward_ratio >= 2 ? "var(--green)" : "var(--yellow)",
                                }}
                            >
                                1:{verdict.risk_reward_ratio.toFixed(2)}
                            </span>
                        </div>
                    )}
                </div>
            )}

            {/* ── Constitution Scores ── */}
            {verdict.scores && (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    <div
                        style={{
                            fontSize: 9,
                            fontWeight: 700,
                            letterSpacing: "0.10em",
                            color: "var(--text-muted)",
                            fontFamily: "var(--font-mono)",
                        }}
                    >
                        CONSTITUTIONAL SCORES
                    </div>
                    <ScoreBar label="WOLF (L1-L6)" value={verdict.scores.wolf_score} max={30} threshold={21} />
                    <ScoreBar label="TII (L8)" value={verdict.scores.tii_score} max={1} threshold={0.90} />
                    <ScoreBar label="FRPC (L9)" value={verdict.scores.frpc_score} max={1} threshold={0.93} />

                    {/* Wolf 30-point breakdown */}
                    {verdict.scores.f_score != null && (
                        <div style={{ marginTop: 4, display: "flex", flexDirection: "column", gap: 6 }}>
                            <div
                                style={{
                                    fontSize: 9,
                                    fontWeight: 700,
                                    letterSpacing: "0.10em",
                                    color: "var(--text-faint)",
                                    fontFamily: "var(--font-mono)",
                                }}
                            >
                                WOLF BREAKDOWN
                            </div>
                            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 6 }}>
                                {([
                                    { label: "F (Fundamental)", value: verdict.scores.f_score ?? 0, max: 8 },
                                    { label: "T (Technical)", value: verdict.scores.t_score ?? 0, max: 12 },
                                    { label: "FTA (Alignment)", value: verdict.scores.fta_score ?? 0, max: 5 },
                                    { label: "E (Execution)", value: verdict.scores.exec_score ?? 0, max: 5 },
                                ] as const).map(({ label, value, max }) => {
                                    const pct = max > 0 ? Math.round((value / max) * 100) : 0;
                                    return (
                                        <div
                                            key={label}
                                            style={{
                                                padding: "6px 8px",
                                                borderRadius: 4,
                                                background: "rgba(0,0,0,0.2)",
                                                border: "1px solid rgba(255,255,255,0.04)",
                                            }}
                                        >
                                            <div style={{ fontSize: 8, color: "var(--text-faint)", letterSpacing: "0.06em", marginBottom: 2 }}>
                                                {label}
                                            </div>
                                            <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
                                                <span className="num" style={{ fontSize: 14, fontWeight: 700, color: pct >= 70 ? "var(--green)" : "var(--text-secondary)" }}>
                                                    {value}
                                                </span>
                                                <span style={{ fontSize: 10, color: "var(--text-muted)" }}>/ {max}</span>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}

                    {/* Regime & Session */}
                    {(verdict.scores.regime || verdict.scores.session) && (
                        <div style={{ display: "flex", gap: 8, marginTop: 2 }}>
                            {verdict.scores.regime && (
                                <div
                                    style={{
                                        flex: 1,
                                        padding: "6px 8px",
                                        borderRadius: 4,
                                        background: "rgba(0,0,0,0.2)",
                                        border: "1px solid rgba(255,255,255,0.04)",
                                    }}
                                >
                                    <div style={{ fontSize: 8, color: "var(--text-faint)", letterSpacing: "0.06em", marginBottom: 2 }}>REGIME</div>
                                    <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>
                                        {verdict.scores.regime}
                                    </div>
                                </div>
                            )}
                            {verdict.scores.session && (
                                <div
                                    style={{
                                        flex: 1,
                                        padding: "6px 8px",
                                        borderRadius: 4,
                                        background: "rgba(0,0,0,0.2)",
                                        border: "1px solid rgba(255,255,255,0.04)",
                                    }}
                                >
                                    <div style={{ fontSize: 8, color: "var(--text-faint)", letterSpacing: "0.06em", marginBottom: 2 }}>SESSION</div>
                                    <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>
                                        {verdict.scores.session}
                                    </div>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}

            {/* ── Gate Analysis ── */}
            {verdict.gates?.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    <div
                        style={{
                            fontSize: 9,
                            fontWeight: 700,
                            letterSpacing: "0.10em",
                            color: "var(--text-muted)",
                            fontFamily: "var(--font-mono)",
                        }}
                    >
                        9-GATE ANALYSIS
                    </div>
                    <GateStatus gates={verdict.gates} />
                </div>
            )}

            {/* ── Timestamp ── */}
            <div
                style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    paddingTop: 8,
                    borderTop: "1px solid rgba(255,255,255,0.06)",
                    fontSize: 10,
                    color: "var(--text-faint)",
                    fontFamily: "var(--font-mono)",
                }}
            >
                <span>LAST UPDATE</span>
                <span>{formatTime(verdict.timestamp * 1000)}</span>
            </div>
        </div>
    );
}
