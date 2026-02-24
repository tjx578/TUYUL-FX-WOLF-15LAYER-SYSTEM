"use client";

/**
 * DisciplineChecklist — Wolf 30-Point Discipline Checklist
 *
 * Complete F7 + T13 + FTA4 + Exec6 checklist visualization.
 * Each item shows pass/fail status with scoring.
 *
 * Designed for the Wolf Discipline page, but can also render
 * as a compact summary in sidebar widgets.
 *
 * Props:
 *   checklist: ChecklistData (from L4 pipeline output)
 *   variant?: "full" | "compact"
 */

import React, { useState, useMemo } from "react";

// ── Types ───────────────────────────────────────────────────────

export interface ChecklistItem {
  id: string;
  label: string;
  passed: boolean;
  weight: number;
  note?: string;
}

export interface ChecklistSection {
  key: string;
  label: string;
  color: string;
  maxPoints: number;
  items: ChecklistItem[];
}

export interface ChecklistData {
  sections: ChecklistSection[];
  timestamp?: string;
}

interface DisciplineChecklistProps {
  checklist: ChecklistData;
  variant?: "full" | "compact";
}

// ── Component ───────────────────────────────────────────────────

export function DisciplineChecklist({
  checklist,
  variant = "full",
}: DisciplineChecklistProps): React.ReactElement {
  const [expandedSection, setExpandedSection] = useState<string | null>(
    null
  );

  const totals = useMemo(() => {
    let scored = 0;
    let max = 0;
    for (const section of checklist.sections) {
      for (const item of section.items) {
        if (item.passed) scored += item.weight;
        max += item.weight;
      }
    }
    return { scored, max };
  }, [checklist]);

  if (variant === "compact") {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {checklist.sections.map((section) => {
          const sectionScore = section.items
            .filter((i) => i.passed)
            .reduce((s, i) => s + i.weight, 0);
          const pct = (sectionScore / section.maxPoints) * 100;

          return (
            <div
              key={section.key}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}
            >
              <span
                style={{
                  fontSize: 10,
                  color: section.color,
                  fontWeight: 700,
                  width: 32,
                }}
              >
                {section.key}
              </span>
              <div
                style={{
                  flex: 1,
                  height: 6,
                  background: "#111",
                  borderRadius: 3,
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    height: "100%",
                    borderRadius: 3,
                    background: section.color,
                    width: `${pct}%`,
                    transition: "width 0.5s ease",
                  }}
                />
              </div>
              <span
                style={{
                  fontSize: 10,
                  color: "#888",
                  fontVariantNumeric: "tabular-nums",
                  width: 36,
                  textAlign: "right",
                }}
              >
                {sectionScore}/{section.maxPoints}
              </span>
            </div>
          );
        })}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            paddingTop: 6,
            borderTop: "1px solid #1a1a1a",
          }}
        >
          <span style={{ fontSize: 10, color: "#888" }}>Total</span>
          <span
            style={{
              fontSize: 12,
              fontWeight: 700,
              color:
                totals.scored >= 27
                  ? "#d4af37"
                  : totals.scored >= 22
                    ? "#10b981"
                    : totals.scored >= 18
                      ? "#f59e0b"
                      : "#ef4444",
            }}
          >
            {totals.scored}/{totals.max}
          </span>
        </div>
      </div>
    );
  }

  // Full variant
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {checklist.sections.map((section) => {
        const sectionScore = section.items
          .filter((i) => i.passed)
          .reduce((s, i) => s + i.weight, 0);
        const isExpanded = expandedSection === section.key;

        return (
          <div
            key={section.key}
            style={{
              background: "#0d0d0d",
              border: `1px solid ${
                isExpanded ? `${section.color}44` : "#1a1a1a"
              }`,
              borderRadius: 10,
              overflow: "hidden",
              transition: "border-color 0.2s",
            }}
          >
            {/* Section header */}
            <div
              onClick={() =>
                setExpandedSection(isExpanded ? null : section.key)
              }
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "12px 16px",
                cursor: "pointer",
                borderBottom: isExpanded
                  ? `1px solid ${section.color}22`
                  : "none",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                }}
              >
                <div
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: 2,
                    background: section.color,
                  }}
                />
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: 700,
                    color: "#ddd",
                  }}
                >
                  {section.label}
                </span>
                <span
                  style={{
                    fontSize: 10,
                    color: "#555",
                  }}
                >
                  ({section.key})
                </span>
              </div>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                }}
              >
                <span
                  style={{
                    fontSize: 14,
                    fontWeight: 700,
                    color: section.color,
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {sectionScore}
                  <span style={{ fontSize: 10, color: "#444" }}>
                    /{section.maxPoints}
                  </span>
                </span>
                <span
                  style={{
                    fontSize: 12,
                    color: "#444",
                    transform: isExpanded
                      ? "rotate(90deg)"
                      : "rotate(0)",
                    transition: "transform 0.2s",
                  }}
                >
                  ▸
                </span>
              </div>
            </div>

            {/* Items (expanded) */}
            {isExpanded && (
              <div
                style={{
                  padding: "8px 16px 12px",
                  display: "flex",
                  flexDirection: "column",
                  gap: 2,
                }}
              >
                {section.items.map((item) => (
                  <div
                    key={item.id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      padding: "5px 8px",
                      borderRadius: 6,
                      background: item.passed
                        ? `${section.color}08`
                        : "#ef444408",
                    }}
                  >
                    <span
                      style={{
                        fontSize: 12,
                        width: 16,
                        color: item.passed ? "#10b981" : "#ef4444",
                      }}
                    >
                      {item.passed ? "✓" : "✗"}
                    </span>
                    <span
                      style={{
                        fontSize: 11,
                        color: item.passed ? "#ccc" : "#666",
                        flex: 1,
                      }}
                    >
                      {item.label}
                    </span>
                    <span
                      style={{
                        fontSize: 10,
                        color: section.color,
                        fontWeight: 700,
                        opacity: 0.7,
                      }}
                    >
                      {item.id}
                    </span>
                    {item.note && (
                      <span
                        style={{
                          fontSize: 9,
                          color: "#555",
                          maxWidth: 120,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                        title={item.note}
                      >
                        {item.note}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default DisciplineChecklist;
