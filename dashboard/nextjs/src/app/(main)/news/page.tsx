"use client";

import { useState } from "react";
import { newsMock } from "@/lib/mock/news";

/* ---- Tab constants ---- */
const TAB_IDS = ["calendar", "headlines", "heatmap", "cross"] as const;
const TAB_LABELS: Record<string, string> = {
  calendar: "CALENDAR",
  headlines: "HEADLINES",
  heatmap: "HEATMAP",
  cross: "CROSS IMPACT",
};

/* ---- Placeholder ---- */
function Placeholder({ title, desc }: { title: string; desc: string }) {
  return (
    <div
      style={{
        background: "#1B1D21",
        border: "1px solid #30343C",
        borderRadius: 14,
        padding: "40px 20px",
        textAlign: "center",
      }}
    >
      <div
        style={{
          color: "#717886",
          fontSize: 11,
          textTransform: "uppercase",
          letterSpacing: "0.12em",
          fontWeight: 700,
        }}
      >
        {title}
      </div>
      <p
        style={{
          color: "#A5ADBA",
          fontSize: 14,
          marginTop: 12,
          maxWidth: 500,
          marginInline: "auto",
        }}
      >
        {desc}
      </p>
    </div>
  );
}

export default function NewsPage() {
  const [tab, setTab] = useState<string>("calendar");
  const calendar = newsMock.calendar;
  const headlines = newsMock.headlines;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Tabs */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 6,
          background: "#1B1D21",
          borderRadius: 12,
          padding: 4,
          border: "1px solid #30343C",
        }}
      >
        {TAB_IDS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              background: tab === t ? "#23262C" : "transparent",
              border:
                tab === t
                  ? "1px solid #30343C"
                  : "1px solid transparent",
              borderRadius: 10,
              padding: "10px 0",
              color: tab === t ? "#C8FF1A" : "#717886",
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: "0.1em",
              cursor: "pointer",
              transition: "all 0.15s",
            }}
          >
            {TAB_LABELS[t]}
          </button>
        ))}
      </div>

      {/* Calendar + Headlines (default view) */}
      {tab === "calendar" && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1.2fr 0.8fr",
            gap: 14,
          }}
        >
          {/* Calendar Table */}
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
              Economic Calendar
            </h3>
            <div style={{ overflow: "hidden", borderRadius: 10 }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    {[
                      "Time",
                      "Country",
                      "Event",
                      "Actual",
                      "Forecast",
                      "Previous",
                    ].map((h) => (
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
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {calendar.map((e, i) => (
                    <tr key={i}>
                      <td
                        style={{
                          padding: "10px 10px",
                          borderBottom: "1px solid #30343C",
                          color: "#C8FF1A",
                          fontFamily: "monospace",
                          fontWeight: 700,
                        }}
                      >
                        {e.time}
                      </td>
                      <td
                        style={{
                          padding: "10px 10px",
                          borderBottom: "1px solid #30343C",
                          color: "#F5F7FA",
                        }}
                      >
                        {e.country}
                      </td>
                      <td
                        style={{
                          padding: "10px 10px",
                          borderBottom: "1px solid #30343C",
                          color: "#F5F7FA",
                          fontWeight: 600,
                        }}
                      >
                        {e.event}
                      </td>
                      <td
                        style={{
                          padding: "10px 10px",
                          borderBottom: "1px solid #30343C",
                          color: "#F5F7FA",
                          fontFamily: "monospace",
                        }}
                      >
                        {e.actual}
                      </td>
                      <td
                        style={{
                          padding: "10px 10px",
                          borderBottom: "1px solid #30343C",
                          color: "#A5ADBA",
                          fontFamily: "monospace",
                        }}
                      >
                        {e.forecast}
                      </td>
                      <td
                        style={{
                          padding: "10px 10px",
                          borderBottom: "1px solid #30343C",
                          color: "#717886",
                          fontFamily: "monospace",
                        }}
                      >
                        {e.previous}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Headlines */}
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
              Headlines
            </h3>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 10,
              }}
            >
              {headlines.map((h, i) => (
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
                      fontWeight: 700,
                      fontSize: 14,
                      color: "#C8FF1A",
                      marginBottom: 4,
                    }}
                  >
                    {h.title}
                  </div>
                  <div style={{ color: "#A5ADBA", fontSize: 13 }}>
                    {h.summary}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {tab === "headlines" && (
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
            All Headlines
          </h3>
          <div
            style={{ display: "flex", flexDirection: "column", gap: 10 }}
          >
            {headlines.map((h, i) => (
              <div
                key={i}
                style={{
                  background: "#23262C",
                  border: "1px solid #30343C",
                  borderRadius: 12,
                  padding: "14px 16px",
                }}
              >
                <div
                  style={{
                    fontWeight: 700,
                    fontSize: 15,
                    color: "#C8FF1A",
                    marginBottom: 6,
                  }}
                >
                  {h.title}
                </div>
                <div style={{ color: "#A5ADBA", fontSize: 14 }}>
                  {h.summary}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === "heatmap" && (
        <Placeholder
          title="CURRENCY HEATMAP"
          desc="Live currency strength visualization across major pairs."
        />
      )}
      {tab === "cross" && (
        <Placeholder
          title="CROSS IMPACT"
          desc="Cross-currency correlation and news impact analysis."
        />
      )}
    </div>
  );
}
