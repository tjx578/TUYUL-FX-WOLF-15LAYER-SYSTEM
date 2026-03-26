"use client";

import type { ReactNode } from "react";

export type DomainId = "signals" | "trades" | "accounts" | "journal" | "news" | "risk";

interface DomainHeaderProps {
    domain: DomainId;
    title: string;
    subtitle: string;
    /** Optional right-side slot (buttons, selectors, counters) */
    actions?: ReactNode;
}

/**
 * Unified domain heading with accent-colored top bar.
 * Each domain has its own CSS variable (--domain-{id}) for visual identity.
 */
export function DomainHeader({ domain, title, subtitle, actions }: DomainHeaderProps) {
    const accentVar = `var(--domain-${domain})`;

    return (
        <div
            data-domain={domain}
            style={{
                borderTop: `2px solid ${accentVar}`,
                paddingTop: 16,
                display: "flex",
                alignItems: "flex-start",
                gap: 14,
                flexWrap: "wrap",
            }}
        >
            <div style={{ minWidth: 0 }}>
                <h1
                    style={{
                        fontSize: 22,
                        fontWeight: 800,
                        letterSpacing: "0.06em",
                        color: accentVar,
                        margin: 0,
                        fontFamily: "var(--font-display)",
                    }}
                >
                    {title}
                </h1>
                <p
                    style={{
                        fontSize: 11,
                        color: "var(--text-muted)",
                        marginTop: 3,
                    }}
                >
                    {subtitle}
                </p>
            </div>

            {actions && <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>{actions}</div>}
        </div>
    );
}
