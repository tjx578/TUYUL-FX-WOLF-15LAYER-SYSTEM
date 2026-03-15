"use client";

// ============================================================
// TUYUL FX Wolf-15 — RecentChangesPanel
// PRD: Command Center — recent WS alerts / changes feed
// ============================================================

interface AlertEvent {
  alert_id?: string;
  type?: string;
  severity?: "INFO" | "WARNING" | "CRITICAL";
  message?: string;
  pair?: string;
  timestamp?: string;
}

interface RecentChangesPanelProps {
  alerts: unknown[];
}

function severityColor(severity?: string): string {
  if (severity === "CRITICAL") return "var(--red)";
  if (severity === "WARNING")  return "var(--yellow)";
  return "var(--text-muted)";
}

function alertBorderColor(severity?: string): string {
  if (severity === "CRITICAL") return "var(--red)";
  if (severity === "WARNING")  return "var(--yellow)";
  return "var(--border-default)";
}

export default function RecentChangesPanel({ alerts }: RecentChangesPanelProps) {
  if (alerts.length === 0) return null;

  return (
    <div
      className="panel"
      style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 8 }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: "0.12em",
            color: "var(--text-muted)",
          }}
        >
          RECENT CHANGES
        </span>
        <span
          style={{
            marginLeft: "auto",
            fontFamily: "var(--font-mono)",
            fontSize: 9,
            color: "var(--text-faint)",
            padding: "1px 5px",
            borderRadius: 3,
            background: "rgba(255,255,255,0.04)",
          }}
        >
          {alerts.length}
        </span>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {alerts.map((a, idx) => {
          const alert = a as AlertEvent;
          const message =
            typeof a === "string"
              ? a
              : alert.message ?? alert.type ?? JSON.stringify(a);
          const severity = alert.severity;
          const pair = alert.pair;

          return (
            <div
              key={alert.alert_id ?? idx}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: 8,
                paddingLeft: 8,
                borderLeft: `2px solid ${alertBorderColor(severity)}`,
              }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    flexWrap: "wrap",
                  }}
                >
                  {severity && severity !== "INFO" && (
                    <span
                      style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: 8,
                        fontWeight: 800,
                        color: severityColor(severity),
                        letterSpacing: "0.08em",
                        flexShrink: 0,
                      }}
                    >
                      {severity}
                    </span>
                  )}
                  {pair && (
                    <span
                      style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: 9,
                        color: "var(--accent)",
                        fontWeight: 700,
                        flexShrink: 0,
                      }}
                    >
                      {pair}
                    </span>
                  )}
                </div>
                <span
                  style={{
                    fontSize: 11,
                    color: "var(--text-secondary)",
                    lineHeight: 1.4,
                    display: "block",
                    marginTop: 2,
                  }}
                >
                  {message}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
