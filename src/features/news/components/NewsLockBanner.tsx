"use client";

export function NewsLockBanner({ reason }: { reason?: string }) {
    return (
        <div
            role="alert"
            className="kill-banner panel"
            style={{
                padding: "12px 16px",
                display: "flex",
                alignItems: "center",
                gap: 12,
                borderColor: "var(--border-danger)",
                background: "var(--red-glow)",
            }}
        >
            <span
                style={{
                    width: 8,
                    height: 8,
                    borderRadius: "50%",
                    background: "var(--red)",
                    display: "inline-block",
                    animation: "pulse-dot 1.2s ease-in-out infinite",
                    flexShrink: 0,
                }}
            />
            <div>
                <div style={{ fontFamily: "var(--font-display)", fontSize: 12, fontWeight: 800, color: "var(--red)", letterSpacing: "0.06em" }}>
                    NEWS LOCK ACTIVE — TRADING RESTRICTED
                </div>
                {reason && (
                    <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>{reason}</div>
                )}
            </div>
        </div>
    );
}
