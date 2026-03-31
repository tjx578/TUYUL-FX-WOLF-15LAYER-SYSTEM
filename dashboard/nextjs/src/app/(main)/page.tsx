"use client";

/* Dashboard Overview -- operator summary */

import { signalsMock } from "@/lib/mock/signals";
import { riskMock } from "@/lib/mock/risk";

/* Hero Card */
function HeroCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub: string;
}) {
  return (
    <div
      style={{
        background: "linear-gradient(135deg, #1B1D21 0%, #23262C 100%)",
        border: "1px solid #30343C",
        borderRadius: 16,
        padding: "20px 22px",
      }}
    >
      <div
        style={{
          color: "#A5ADBA",
          fontSize: 11,
          textTransform: "uppercase",
          letterSpacing: "0.1em",
          fontWeight: 700,
        }}
      >
        {label}
      </div>
      <div
        style={{ fontSize: 32, fontWeight: 800, marginTop: 8, color: "#F5F7FA" }}
      >
        {value}
      </div>
      <div style={{ color: "#717886", fontSize: 13, marginTop: 6 }}>{sub}</div>
    </div>
  );
}

/* Metric Card */
function MetricCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
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
      <div
        style={{
          fontSize: 26,
          fontWeight: 800,
          marginTop: 8,
          color: color ?? "#F5F7FA",
        }}
      >
        {value}
      </div>
    </div>
  );
}

/* Bias Pill */
const BIAS_COLOR: Record<string, string> = {
  BUY: "#32D583",
  SELL: "#FF4D4F",
  HOLD: "#ffd740",
};

function BiasPill({ bias }: { bias: string }) {
  const c = BIAS_COLOR[bias] ?? "#A5ADBA";
  return (
    <span
      style={{
        display: "inline-block",
        padding: "3px 10px",
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: "0.06em",
        background: `${c}18`,
        color: c,
        border: `1px solid ${c}30`,
      }}
    >
      {bias}
    </span>
  );
}

/* Severity Pill */
function SeverityPill({ level }: { level?: string }) {
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
      {level ?? "info"}
    </span>
  );
}

export default function DashboardPage() {
  const signals = signalsMock.items;
  const warnings = riskMock.warnings;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* A. Hero Cards */}
      <div
        style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14 }}
      >
        <HeroCard
          label="System Truth"
          value="ONLINE"
          sub="15-layer pipeline healthy"
        />
        <HeroCard
          label="Capital Focus"
          value="$154,320"
          sub="3 accounts linked"
        />
        <HeroCard
          label="Action Window"
          value="London"
          sub="High-probability session active"
        />
      </div>

      {/* B. Metric Cards */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 12,
        }}
      >
        <MetricCard label="Pending Signals" value="12" />
        <MetricCard label="Ready to Execute" value="5" color="#32D583" />
        <MetricCard label="Open Trades" value="3" />
        <MetricCard label="Daily DD" value="1.1%" color="#FF4D4F" />
      </div>

      {/* C + D: Top Signals + Risk Alerts */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1.4fr 0.6fr",
          gap: 14,
        }}
      >
        {/* C. Top Signals Table */}
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
            Top Signals
          </h3>
          <div style={{ overflow: "hidden", borderRadius: 10 }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  {["Pair", "Bias", "Confidence", "Session", "Action"].map(
                    (h) => (
                      <th
                        key={h}
                        style={{
                          padding: "10px 10px",
                          borderBottom: "1px solid #30343C",
                          textAlign: "left",
                          color: "#A5ADBA",
                          fontSize: 11,
                          textTransform: "uppercase",
                          letterSpacing: "0.06em",
                          background: "#23262C",
                        }}
                      >
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {signals.map((s) => (
                  <tr key={s.id}>
                    <td
                      style={{
                        padding: "10px 10px",
                        borderBottom: "1px solid #30343C",
                        fontWeight: 700,
                        color: "#F5F7FA",
                      }}
                    >
                      {s.pair}
                    </td>
                    <td
                      style={{
                        padding: "10px 10px",
                        borderBottom: "1px solid #30343C",
                      }}
                    >
                      <BiasPill bias={s.bias} />
                    </td>
                    <td
                      style={{
                        padding: "10px 10px",
                        borderBottom: "1px solid #30343C",
                        color: s.confidence >= 80 ? "#32D583" : "#A5ADBA",
                        fontWeight: 700,
                      }}
                    >
                      {s.confidence}%
                    </td>
                    <td
                      style={{
                        padding: "10px 10px",
                        borderBottom: "1px solid #30343C",
                        color: "#A5ADBA",
                      }}
                    >
                      {s.session}
                    </td>
                    <td
                      style={{
                        padding: "10px 10px",
                        borderBottom: "1px solid #30343C",
                      }}
                    >
                      <button
                        style={{
                          background: "transparent",
                          border: "1px solid #30343C",
                          borderRadius: 8,
                          color: "#C8FF1A",
                          padding: "4px 12px",
                          cursor: "pointer",
                          fontSize: 11,
                          fontWeight: 700,
                        }}
                      >
                        VIEW
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* D. Risk Alerts */}
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
            Risk Alerts
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
                    style={{ fontWeight: 700, fontSize: 14, color: "#F5F7FA" }}
                  >
                    {w.title}
                  </span>
                  <SeverityPill
                    level={
                      i === 2 ? "high" : i === 1 ? "medium" : "info"
                    }
                  />
                </div>
                <div style={{ color: "#A5ADBA", fontSize: 13 }}>{w.desc}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
