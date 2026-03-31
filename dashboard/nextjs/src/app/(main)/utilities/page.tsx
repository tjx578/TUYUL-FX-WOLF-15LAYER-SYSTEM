"use client";

import { utilitiesMock } from "@/lib/mock/utilities";

/* Icon placeholders mapped by title */
const ICON: Record<string, string> = {
  "MT5 Web": "MT5",
  cTrader: "cT",
  MatchTrader: "MT",
  "Currency Heatmap": "HM",
  "Lotsize Tool": "LS",
  "Account Sync": "SY",
};

export default function UtilitiesPage() {
  const tools = utilitiesMock.items;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <h2
        style={{
          margin: 0,
          fontSize: 18,
          fontWeight: 700,
          color: "#F5F7FA",
        }}
      >
        Utilities
      </h2>

      {/* 3-Column Grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 14,
        }}
      >
        {tools.map((tool) => (
          <div
            key={tool.title}
            style={{
              background: "#1B1D21",
              border: "1px solid #30343C",
              borderRadius: 14,
              padding: 20,
              minHeight: 150,
              cursor: "pointer",
              transition: "border-color 0.15s",
            }}
            onMouseEnter={(e) =>
              (e.currentTarget.style.borderColor = "#C8FF1A40")
            }
            onMouseLeave={(e) =>
              (e.currentTarget.style.borderColor = "#30343C")
            }
          >
            {/* Icon Badge */}
            <div
              style={{
                width: 44,
                height: 44,
                borderRadius: 12,
                background: "#23262C",
                border: "1px solid #30343C",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                marginBottom: 14,
                color: "#C8FF1A",
                fontWeight: 800,
                fontSize: 14,
                letterSpacing: "0.04em",
              }}
            >
              {ICON[tool.title] ?? "?"}
            </div>
            <h4
              style={{
                margin: "0 0 6px",
                fontWeight: 700,
                fontSize: 15,
                color: "#F5F7FA",
              }}
            >
              {tool.title}
            </h4>
            <div style={{ color: "#A5ADBA", fontSize: 13 }}>{tool.desc}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
