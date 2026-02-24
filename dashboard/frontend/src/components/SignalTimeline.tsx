"use client";

/**
 * SignalTimeline — Signal Lifecycle Timeline Component
 *
 * Visual timeline showing:
 * - Signal generation → gate evaluation → verdict → execution → reflection
 * - Each step with timestamp, status, and metadata
 * - Color-coded by outcome (accepted/rejected/pending)
 *
 * Props:
 *   events: SignalEvent[] (from trade journal / WS stream)
 *   compact?: boolean
 */

import React from "react";

// ── Types ───────────────────────────────────────────────────────

export type SignalEventType =
  | "SIGNAL_GENERATED"
  | "GATES_EVALUATED"
  | "VERDICT_ISSUED"
  | "RISK_CALCULATED"
  | "ORDER_SENT"
  | "ORDER_FILLED"
  | "TP_HIT"
  | "SL_HIT"
  | "MANUAL_CLOSE"
  | "REFLECTION"
  | "REJECTED";

export interface SignalEvent {
  id: string;
  type: SignalEventType;
  timestamp: string;
  label: string;
  detail: string;
  metadata?: Record<string, string | number | boolean>;
}

interface SignalTimelineProps {
  events: SignalEvent[];
  compact?: boolean;
}

// ── Constants ───────────────────────────────────────────────────

const EVENT_COLORS: Record<SignalEventType, string> = {
  SIGNAL_GENERATED: "#3b82f6",
  GATES_EVALUATED: "#a855f7",
  VERDICT_ISSUED: "#d4af37",
  RISK_CALCULATED: "#f59e0b",
  ORDER_SENT: "#10b981",
  ORDER_FILLED: "#10b981",
  TP_HIT: "#10b981",
  SL_HIT: "#ef4444",
  MANUAL_CLOSE: "#6b7280",
  REFLECTION: "#8b5cf6",
  REJECTED: "#ef4444",
};

const EVENT_ICONS: Record<SignalEventType, string> = {
  SIGNAL_GENERATED: "◈",
  GATES_EVALUATED: "⊞",
  VERDICT_ISSUED: "◉",
  RISK_CALCULATED: "⛨",
  ORDER_SENT: "▸",
  ORDER_FILLED: "●",
  TP_HIT: "✓",
  SL_HIT: "✗",
  MANUAL_CLOSE: "■",
  REFLECTION: "◇",
  REJECTED: "⊘",
};

// ── Component ───────────────────────────────────────────────────

export function SignalTimeline({
  events,
  compact = false,
}: SignalTimelineProps): React.ReactElement {
  if (events.length === 0) {
    return (
      <div
        style={{
          padding: 20,
          textAlign: "center",
          color: "#444",
          fontSize: 12,
        }}
      >
        No signal events yet
      </div>
    );
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        position: "relative",
      }}
    >
      {/* Vertical line */}
      <div
        style={{
          position: "absolute",
          left: compact ? 8 : 12,
          top: 4,
          bottom: 4,
          width: 1,
          background: "#1a1a1a",
        }}
      />

      {events.map((event, idx) => {
        const color = EVENT_COLORS[event.type];
        const icon = EVENT_ICONS[event.type];
        const time = event.timestamp.slice(11, 19); // HH:MM:SS

        if (compact) {
          return (
            <div
              key={event.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "4px 0",
                position: "relative",
              }}
            >
              {/* Dot */}
              <div
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: "50%",
                  background: color,
                  flexShrink: 0,
                  position: "relative",
                  zIndex: 1,
                  marginLeft: 5,
                }}
              />
              <span
                style={{
                  fontSize: 9,
                  color: "#555",
                  fontVariantNumeric: "tabular-nums",
                  width: 48,
                }}
              >
                {time}
              </span>
              <span
                style={{
                  fontSize: 10,
                  color: color,
                  fontWeight: 600,
                }}
              >
                {event.label}
              </span>
            </div>
          );
        }

        return (
          <div
            key={event.id}
            style={{
              display: "flex",
              gap: 14,
              padding: "8px 0",
              position: "relative",
            }}
          >
            {/* Icon */}
            <div
              style={{
                width: 24,
                height: 24,
                borderRadius: 6,
                background: `${color}18`,
                border: `1px solid ${color}33`,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 12,
                color: color,
                flexShrink: 0,
                position: "relative",
                zIndex: 1,
              }}
            >
              {icon}
            </div>

            {/* Content */}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: 2,
                }}
              >
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: 700,
                    color: color,
                  }}
                >
                  {event.label}
                </span>
                <span
                  style={{
                    fontSize: 10,
                    color: "#555",
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {time}
                </span>
              </div>
              <div
                style={{
                  fontSize: 11,
                  color: "#888",
                  lineHeight: 1.4,
                }}
              >
                {event.detail}
              </div>

              {/* Metadata tags */}
              {event.metadata &&
                Object.keys(event.metadata).length > 0 && (
                  <div
                    style={{
                      display: "flex",
                      gap: 6,
                      flexWrap: "wrap",
                      marginTop: 6,
                    }}
                  >
                    {Object.entries(event.metadata).map(
                      ([key, val]) => (
                        <span
                          key={key}
                          style={{
                            fontSize: 9,
                            padding: "2px 6px",
                            borderRadius: 4,
                            background: "#111",
                            border: "1px solid #222",
                            color: "#666",
                          }}
                        >
                          {key}: {String(val)}
                        </span>
                      )
                    )}
                  </div>
                )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default SignalTimeline;
