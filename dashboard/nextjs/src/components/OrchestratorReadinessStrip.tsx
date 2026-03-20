"use client";

import React from "react";
import { useOrchestratorState } from "@/lib/api";

export default function OrchestratorReadinessStrip() {
    const { data: orchestrator, isLoading } = useOrchestratorState();

    const ready = orchestrator?.orchestrator_ready === true;
    const statusLabel = isLoading
        ? "CHECKING"
        : orchestrator?.orchestrator_ready === undefined
            ? "UNKNOWN"
            : ready
                ? "READY"
                : (orchestrator?.mode ?? "NOT_READY");

    const statusColor =
        statusLabel === "READY"
            ? "var(--green)"
            : statusLabel === "CHECKING" || statusLabel === "UNKNOWN"
                ? "var(--yellow)"
                : "var(--red)";

    const hbAge = orchestrator?.orchestrator_heartbeat_age_seconds;

    return (
        <div
            role="status"
            aria-label="Orchestrator readiness"
            className="panel"
            style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 12,
                padding: "10px 12px",
            }}
        >
            <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                <span
                    style={{
                        width: 8,
                        height: 8,
                        borderRadius: "50%",
                        background: statusColor,
                        animation: ready ? "pulse-dot 1.4s ease-in-out infinite" : "none",
                        flexShrink: 0,
                    }}
                    aria-hidden="true"
                />
                <span style={{ fontSize: 10, letterSpacing: "0.1em", color: "var(--text-muted)", fontWeight: 700 }}>
                    ORCHESTRATOR
                </span>
                <span className="num" style={{ fontSize: 12, fontWeight: 700, color: statusColor }}>
                    {statusLabel}
                </span>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", justifyContent: "flex-end" }}>
                {orchestrator?.mode && (
                    <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
                        mode: <strong style={{ color: "var(--text-secondary)" }}>{orchestrator.mode}</strong>
                    </span>
                )}
                {hbAge !== undefined && hbAge !== null && (
                    <span className="num" style={{ fontSize: 10, color: ready ? "var(--green)" : "var(--yellow)" }}>
                        hb {Math.round(hbAge)}s ago
                    </span>
                )}
            </div>
        </div>
    );
}
