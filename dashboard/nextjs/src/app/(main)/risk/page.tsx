"use client";

import { riskMock } from "@/lib/mock/risk";

/* ---- KPI Card ---- */
function KPICard({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  const c =
    color === "green"
      ? "#32D583"
      : color === "red"
        ? "#FF4D4F"
        : color === "blue"
          ? "#C8FF1A"
          : "#F5F7FA";
  return (
    <div
      style={{
        background: "#1B1D21",
        border: "1px solid #30343C",
        borderRadius: 14,
        padding: 16,
      }}
    >
      <div
        style={{
          color: "#A5ADBA",
          fontSize: 11,
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          fontWeight: 600,
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: 26, fontWeight: 800, marginTop: 8, color: c }}>
        {value}
      </div>
    </div>
  );
}

/* ---- Severity Pill ---- */
function SeverityPill({ level }: { level: string }) {
  const c =
    level === "high"
      ? "#FF4D4F"
      : level === "medium"
        ? "#ffd740"
        : "#A5ADBA";
  return (
    <span
      style={{
        display: "inline-block",
        padding: "3px 10px",
        borderRadius: 999,
        fontSize: 10,
        fontWeight: 700,
        textTransform: "uppercase",
        background: `${c}18`,
        color: c,
        border: `1px solid ${c}30`,
      }}
    >
      {level}
    </span>
  );
}

export default function RiskPage() {
  const cards = riskMock.cards;
  const overview = riskMock.overview;
  const warnings = riskMock.warnings;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* KPI Cards */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 12,
        }}
      >
        {cards.map((c) => (
          <KPICard
            key={c.label}
            label={c.label}
            value={c.value}
            color={"color" in c ? c.color : undefined}
          />
        ))}
      </div>

      {/* 2-Panel: Overview + Warnings */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 14,
        }}
      >
        {/* Overview Table */}
        <div
          style={{
            background: "#1B1D21",
            border: "1px solid #30343C",
            borderRadius: 14,
            padding: 16,
          }}
        >
          <h3
            style={{
              margin: "0 0 14px",
              fontSize: 16,
              fontWeight: 700,
              color: "#F5F7FA",
            }}
          >
            Risk Overview
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
            {overview.map((item, i) => (
              <div
                key={item.key}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  padding: "12px 0",
                  borderBottom:
                    i < overview.length - 1
                      ? "1px solid #30343C"
                      : "none",
                }}
              >
                <span style={{ color: "#A5ADBA", fontSize: 14 }}>
                  {item.key}
                </span>
                <span
                  style={{
                    color: "#F5F7FA",
                    fontWeight: 700,
                    fontSize: 14,
                  }}
                >
                  {item.value}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Warning Stack */}
        <div
          style={{
            background: "#1B1D21",
            border: "1px solid #30343C",
            borderRadius: 14,
            padding: 16,
          }}
        >
          <h3
            style={{
              margin: "0 0 14px",
              fontSize: 16,
              fontWeight: 700,
              color: "#F5F7FA",
            }}
          >
            Active Warnings
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {warnings.map((w, i) => (
              <div
                key={i}
                style={{
                  background: "#23262C",
                  border: "1px solid #30343C",
                  borderRadius: 12,
                  padding: "12px 14px",
                }}
              >
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
                      fontWeight: 700,
                      fontSize: 14,
                      color: "#F5F7FA",
                    }}
                  >
                    {w.title}
                  </span>
                  <SeverityPill
                    level={
                      i === 2 ? "high" : i === 1 ? "medium" : "info"
                    }
                  />
                </div>
                <div style={{ color: "#A5ADBA", fontSize: 13 }}>
                  {w.desc}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
