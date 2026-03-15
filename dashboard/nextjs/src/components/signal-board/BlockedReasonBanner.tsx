"use client";

interface Props {
  reason: string;
  isNewsLock?: boolean;
}

export function BlockedReasonBanner({ reason, isNewsLock }: Props) {
  return (
    <div
      role="alert"
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 10,
        padding: "10px 14px",
        borderRadius: "var(--radius-md)",
        background: "rgba(255,61,87,0.07)",
        border: "1px solid rgba(255,61,87,0.22)",
      }}
    >
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 13,
          color: "var(--red)",
          flexShrink: 0,
          marginTop: 1,
        }}
      >
        ✗
      </span>
      <div style={{ flex: 1 }}>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: "0.12em",
            color: "var(--red)",
            marginBottom: 3,
          }}
        >
          {isNewsLock ? "NEWS BLACKOUT ACTIVE" : "SIGNAL BLOCKED"}
        </div>
        <div
          style={{
            fontSize: 11,
            color: "rgba(255,61,87,0.85)",
            lineHeight: 1.5,
          }}
        >
          {reason}
        </div>
      </div>
    </div>
  );
}
