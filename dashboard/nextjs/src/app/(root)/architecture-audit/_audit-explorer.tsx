"use client";

import { useState } from "react";
import type { ArchDoc, DocDomain } from "./_audit-data";
import { AUDIT_MANIFEST, getDocsByDomain } from "./_audit-data";

// ── Doc card ─────────────────────────────────────────────────

function DocCard({ doc }: { doc: ArchDoc }) {
    const [expanded, setExpanded] = useState(false);

    return (
        <div
            className="card"
            style={{
                padding: 0,
                overflow: "hidden",
                transition: "border-color 0.15s",
            }}
        >
            {/* Header row */}
            <button
                onClick={() => setExpanded((v) => !v)}
                style={{
                    width: "100%",
                    padding: "12px 16px",
                    background: expanded ? "var(--accent-muted)" : "transparent",
                    border: "none",
                    cursor: "pointer",
                    textAlign: "left",
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 12,
                    transition: "background 0.15s",
                }}
            >
                {/* Status badge */}
                <span
                    style={{
                        display: "inline-flex",
                        alignItems: "center",
                        padding: "2px 8px",
                        borderRadius: "var(--radius-sm)",
                        background: "var(--cyan-glow)",
                        border: "1px solid rgba(0,229,255,0.3)",
                        color: "var(--cyan)",
                        fontFamily: "var(--font-mono)",
                        fontSize: 9,
                        fontWeight: 700,
                        letterSpacing: "0.08em",
                        whiteSpace: "nowrap",
                        flexShrink: 0,
                    }}
                >
                    CANONICAL
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-primary)", lineHeight: 1.4 }}>
                        {doc.title}
                    </div>
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
                    {expanded ? "▲" : "▼"}
                </span>
            </button>

            {/* Expanded detail */}
            {expanded && (
                <div
                    style={{
                        padding: "0 16px 14px",
                        display: "flex",
                        flexDirection: "column",
                        gap: 10,
                        borderTop: "1px solid rgba(0,229,255,0.2)",
                    }}
                >
                    <p
                        style={{
                            fontSize: 12,
                            color: "var(--text-secondary)",
                            lineHeight: 1.6,
                            margin: "10px 0 0",
                        }}
                    >
                        {doc.description}
                    </p>
                    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                        <div
                            style={{
                                display: "inline-flex",
                                alignItems: "center",
                                gap: 6,
                                padding: "4px 10px",
                                background: "var(--bg-elevated)",
                                borderRadius: "var(--radius-sm)",
                                border: "1px solid var(--border-default)",
                            }}
                        >
                            <span style={{ fontSize: 9, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>PATH</span>
                            <span style={{ fontSize: 10, color: "var(--accent)", fontFamily: "var(--font-mono)", fontWeight: 600 }}>
                                {doc.path}
                            </span>
                        </div>
                        <span
                            style={{
                                fontSize: 9,
                                color: "var(--text-faint)",
                                fontFamily: "var(--font-mono)",
                            }}
                        >
                            updated {doc.last_updated}
                        </span>
                    </div>
                </div>
            )}
        </div>
    );
}

// ── Domain tab button ─────────────────────────────────────────

function DomainTab({
    domain,
    count,
    isActive,
    onClick,
}: {
    domain: DocDomain;
    count: number;
    isActive: boolean;
    onClick: () => void;
}) {
    return (
        <button
            onClick={onClick}
            aria-pressed={isActive}
            style={{
                padding: "10px 12px",
                borderRadius: "var(--radius-md)",
                border: `1px solid ${isActive ? "var(--accent)" : "var(--border-default)"}`,
                background: isActive ? "var(--accent-muted)" : "var(--bg-card)",
                cursor: "pointer",
                textAlign: "left",
                display: "flex",
                flexDirection: "column",
                gap: 5,
            }}
        >
            <div
                style={{
                    fontSize: 11,
                    fontWeight: isActive ? 700 : 500,
                    color: isActive ? "var(--accent)" : "var(--text-secondary)",
                    lineHeight: 1.3,
                }}
            >
                {domain.label}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span
                    style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: 10,
                        fontWeight: 700,
                        color: isActive ? "var(--cyan)" : "var(--text-muted)",
                    }}
                >
                    {count}
                </span>
                <span style={{ fontSize: 9, color: "var(--text-faint)", fontFamily: "var(--font-mono)" }}>
                    {count === 1 ? "doc" : "docs"}
                </span>
            </div>
        </button>
    );
}

// ── DocExplorer (client component) ───────────────────────────

export function DocExplorer() {
    const [activeDomainId, setActiveDomainId] = useState<string>(
        AUDIT_MANIFEST.domains[0]?.id ?? "core"
    );

    const activeDomain = AUDIT_MANIFEST.domains.find((d) => d.id === activeDomainId);
    const docs = getDocsByDomain(activeDomainId);

    // Pre-compute doc counts per domain for tab display
    const docCounts: Record<string, number> = {};
    for (const domain of AUDIT_MANIFEST.domains) {
        docCounts[domain.id] = getDocsByDomain(domain.id).length;
    }

    return (
        <div style={{ display: "grid", gridTemplateColumns: "220px 1fr", gap: 14 }}>

            {/* ── Left: domain list ── */}
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {AUDIT_MANIFEST.domains.map((domain) => (
                    <DomainTab
                        key={domain.id}
                        domain={domain}
                        count={docCounts[domain.id] ?? 0}
                        isActive={activeDomainId === domain.id}
                        onClick={() => setActiveDomainId(domain.id)}
                    />
                ))}

                {/* ── Manifest meta ── */}
                <div
                    className="card"
                    style={{ padding: "12px 14px", marginTop: 8 }}
                >
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
                        MANIFEST
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        {[
                            { label: "Version", value: AUDIT_MANIFEST.version },
                            { label: "Updated", value: AUDIT_MANIFEST.generated_at },
                            { label: "Source", value: AUDIT_MANIFEST.source },
                            { label: "Total docs", value: String(AUDIT_MANIFEST.docs.length) },
                        ].map(({ label, value }) => (
                            <div key={label} style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                                <span style={{ fontSize: 9, color: "var(--text-faint)", fontFamily: "var(--font-mono)" }}>
                                    {label}
                                </span>
                                <span
                                    style={{
                                        fontSize: 9,
                                        color: "var(--text-secondary)",
                                        fontFamily: "var(--font-mono)",
                                        textAlign: "right",
                                    }}
                                >
                                    {value}
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            </div>

            {/* ── Right: doc list ── */}
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>

                {/* Domain header */}
                {activeDomain && (
                    <div
                        className="card"
                        style={{ padding: "14px 18px" }}
                    >
                        <div
                            style={{
                                fontSize: 16,
                                fontWeight: 800,
                                color: "var(--text-primary)",
                                fontFamily: "var(--font-display)",
                                letterSpacing: "0.04em",
                            }}
                        >
                            {activeDomain.label.toUpperCase()}
                        </div>
                        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4, lineHeight: 1.5 }}>
                            {activeDomain.description}
                        </div>
                        <div
                            style={{
                                marginTop: 8,
                                fontSize: 9,
                                fontFamily: "var(--font-mono)",
                                color: "var(--text-faint)",
                            }}
                        >
                            {docs.length} {docs.length === 1 ? "document" : "documents"}
                        </div>
                    </div>
                )}

                {/* Doc cards */}
                {docs.map((doc) => (
                    <DocCard key={doc.id} doc={doc} />
                ))}

                {docs.length === 0 && (
                    <div
                        className="card"
                        style={{
                            padding: "24px 18px",
                            textAlign: "center",
                            color: "var(--text-muted)",
                            fontSize: 12,
                        }}
                    >
                        No documents in this domain.
                    </div>
                )}
            </div>
        </div>
    );
}
