"use client";

/**
 * PipelineFlow — L1→L15 Pipeline Visualization Component
 *
 * Renders the Wolf 15-Layer pipeline as a visual flow:
 * - 6 zones: COGNITIVE → ANALYSIS → META → EXECUTION → VERDICT → POST
 * - Each layer shows score, status, and detail on expand
 * - Animated progress bars with zone-colored accents
 * - Click-to-expand layer details
 *
 * Props:
 *   layers: LayerStatus[] (from pipeline WebSocket stream)
 *   compact?: boolean (mini mode for sidebar)
 */

import React, { useState } from "react";

// ── Types ───────────────────────────────────────────────────────

export type LayerStatusCode = "PASS" | "FAIL" | "ACTIVE" | "PENDING" | "SKIP";

export interface LayerStatus {
  id: string; // "L1" through "L15"
  name: string;
  score: number; // 0.0 to 1.0
  status: LayerStatusCode;
  detail: string;
  latencyMs?: number;
  timestamp?: string;
}

export type ZoneName =
  | "COGNITIVE"
  | "ANALYSIS"
  | "META"
  | "EXECUTION"
  | "VERDICT"
  | "POST";

interface PipelineFlowProps {
  layers: LayerStatus[];
  compact?: boolean;
  onLayerClick?: (layerId: string) => void;
}

// ── Constants ───────────────────────────────────────────────────

const ZONE_DEFINITIONS: {
  name: ZoneName;
  layers: string[];
  color: string;
  icon: string;
}[] = [
  { name: "COGNITIVE", layers: ["L1", "L2", "L3", "L4"], color: "#3b82f6", icon: "◆" },
  { name: "ANALYSIS", layers: ["L5", "L6", "L7"], color: "#a855f7", icon: "◈" },
  { name: "META", layers: ["L8", "L9"], color: "#f59e0b", icon: "◇" },
  { name: "EXECUTION", layers: ["L10", "L11"], color: "#10b981", icon: "▸" },
  { name: "VERDICT", layers: ["L12"], color: "#d4af37", icon: "◉" },
  { name: "POST", layers: ["L13", "L14", "L15"], color: "#6b7280", icon: "○" },
];

const STATUS_COLORS: Record<LayerStatusCode, string> = {
  PASS: "#10b981",
  FAIL: "#ef4444",
  ACTIVE: "#3b82f6",
  PENDING: "#555555",
  SKIP: "#333333",
};

// ── Component ───────────────────────────────────────────────────

export function PipelineFlow({
  layers,
  compact = false,
  onLayerClick,
}: PipelineFlowProps): React.ReactElement {
  const [expandedLayer, setExpandedLayer] = useState<string | null>(null);

  const layerMap = new Map(layers.map((l) => [l.id, l]));
  const overallHealth =
    layers.length > 0
      ? layers.reduce((sum, l) => sum + l.score, 0) / layers.length
      : 0;
  const allPass = layers.slice(0, 12).every((l) => l.status === "PASS");

  const handleClick = (layerId: string) => {
    setExpandedLayer((prev) => (prev === layerId ? null : layerId));
    onLayerClick?.(layerId);
  };

  if (compact) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        {layers.map((layer) => {
          const zone = ZONE_DEFINITIONS.find((z) =>
            z.layers.includes(layer.id)
          );
          const pct = layer.score * 100;
          return (
            <div
              key={layer.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              <span
                style={{
                  fontSize: 9,
                  color: zone?.color || "#666",
                  fontWeight: 700,
                  width: 20,
                  fontFamily: "monospace",
                }}
              >
                {layer.id}
              </span>
              <div
                style={{
                  flex: 1,
                  height: 4,
                  background: "#111",
                  borderRadius: 2,
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    height: "100%",
                    borderRadius: 2,
                    background: STATUS_COLORS[layer.status],
                    width: `${pct}%`,
                    transition: "width 0.6s ease",
                  }}
                />
              </div>
              <span
                style={{
                  fontSize: 9,
                  color: "#555",
                  width: 28,
                  textAlign: "right",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {pct.toFixed(0)}%
              </span>
            </div>
          );
        })}
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div>
          <div
            style={{
              fontSize: 13,
              fontWeight: 700,
              color: "#ddd",
            }}
          >
            Pipeline Status
          </div>
          <div style={{ fontSize: 10, color: "#555" }}>
            L1→L15 real-time data flow
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: allPass ? "#10b981" : "#ef4444",
              boxShadow: `0 0 6px ${allPass ? "#10b98166" : "#ef444466"}`,
            }}
          />
          <span
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: allPass ? "#10b981" : "#ef4444",
            }}
          >
            {allPass ? "ALL PASS" : "BLOCKED"}
          </span>
          <span
            style={{
              fontSize: 11,
              color: "#555",
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {(overallHealth * 100).toFixed(0)}%
          </span>
        </div>
      </div>

      {/* Zone Flow */}
      {ZONE_DEFINITIONS.map((zone, zoneIdx) => (
        <div key={zone.name}>
          {/* Zone header */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              marginBottom: 8,
            }}
          >
            <span style={{ color: zone.color, fontSize: 12 }}>
              {zone.icon}
            </span>
            <span
              style={{
                fontSize: 10,
                color: zone.color,
                fontWeight: 700,
                letterSpacing: 1.5,
              }}
            >
              {zone.name}
            </span>
            <div
              style={{ flex: 1, height: 1, background: `${zone.color}22` }}
            />
          </div>

          {/* Layer cards */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: `repeat(${Math.min(zone.layers.length, 4)}, 1fr)`,
              gap: 8,
              paddingLeft: 20,
            }}
          >
            {zone.layers.map((lid) => {
              const layer = layerMap.get(lid);
              if (!layer) return null;

              const pct = layer.score * 100;
              const isExpanded = expandedLayer === lid;
              const statusColor = STATUS_COLORS[layer.status];

              return (
                <div
                  key={lid}
                  onClick={() => handleClick(lid)}
                  style={{
                    background: isExpanded
                      ? `${zone.color}0a`
                      : "#0d0d0d",
                    border: `1px solid ${
                      isExpanded ? zone.color : "#1a1a1a"
                    }`,
                    borderRadius: 10,
                    padding: "12px 14px",
                    cursor: "pointer",
                    transition: "all 0.2s",
                  }}
                >
                  {/* Layer header */}
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      marginBottom: 6,
                    }}
                  >
                    <span
                      style={{
                        fontSize: 12,
                        fontWeight: 700,
                        color: zone.color,
                      }}
                    >
                      {lid}
                    </span>
                    <span
                      style={{
                        fontSize: 9,
                        padding: "2px 6px",
                        borderRadius: 4,
                        background: `${statusColor}18`,
                        color: statusColor,
                        fontWeight: 600,
                      }}
                    >
                      {layer.status}
                    </span>
                  </div>

                  {/* Layer name */}
                  <div
                    style={{
                      fontSize: 11,
                      color: "#aaa",
                      marginBottom: 8,
                    }}
                  >
                    {layer.name}
                  </div>

                  {/* Progress bar */}
                  <div
                    style={{
                      height: 4,
                      background: "#1a1a1a",
                      borderRadius: 2,
                      overflow: "hidden",
                    }}
                  >
                    <div
                      style={{
                        height: "100%",
                        borderRadius: 2,
                        background: zone.color,
                        width: `${pct}%`,
                        transition: "width 0.6s ease",
                      }}
                    />
                  </div>

                  {/* Score */}
                  <div
                    style={{
                      fontSize: 10,
                      color: "#555",
                      marginTop: 4,
                      fontVariantNumeric: "tabular-nums",
                    }}
                  >
                    {pct.toFixed(0)}% confidence
                    {layer.latencyMs !== undefined && (
                      <span style={{ marginLeft: 8 }}>
                        {layer.latencyMs}ms
                      </span>
                    )}
                  </div>

                  {/* Expanded detail */}
                  {isExpanded && (
                    <div
                      style={{
                        marginTop: 10,
                        paddingTop: 10,
                        borderTop: `1px solid ${zone.color}25`,
                        fontSize: 11,
                        color: "#999",
                        lineHeight: 1.6,
                      }}
                    >
                      {layer.detail}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Flow arrow between zones */}
          {zoneIdx < ZONE_DEFINITIONS.length - 1 && (
            <div
              style={{
                textAlign: "center",
                color: "#222",
                fontSize: 14,
                margin: "6px 0 2px",
                paddingLeft: 20,
              }}
            >
              ↓
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export default PipelineFlow;
