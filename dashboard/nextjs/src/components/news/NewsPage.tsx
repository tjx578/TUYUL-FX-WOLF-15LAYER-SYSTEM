"use client";

import { useNewsData } from "@/hooks/useNewsData";

export function NewsPage() {
  const { calendar, headlines } = useNewsData();

  return (
    <section>
      <div style={{ display: "grid", gridTemplateColumns: "1.2fr 0.8fr", gap: 14 }}>
        {/* Calendar */}
        <div style={{ background: "#0b0f15", border: "1px solid #232834", borderRadius: 14, padding: 14 }}>
          <h3 style={{ margin: "0 0 12px", fontSize: 18, fontWeight: 700 }}>Economic Calendar</h3>
          {calendar.map((row, i) => (
            <div key={i} style={{ padding: "12px 0", borderBottom: "1px solid #1d2330" }}>
              <strong style={{ color: "#e8eaed" }}>
                {row.time} · {row.country}
              </strong>
              <div style={{ color: "#94a0b4", marginTop: 4 }}>{row.event}</div>
              <div style={{ color: "#717886", fontSize: 12, marginTop: 4 }}>
                Actual: {row.actual} | Forecast: {row.forecast} | Previous: {row.previous}
              </div>
            </div>
          ))}
        </div>

        {/* Headlines */}
        <div style={{ background: "#0b0f15", border: "1px solid #232834", borderRadius: 14, padding: 14 }}>
          <h3 style={{ margin: "0 0 12px", fontSize: 18, fontWeight: 700 }}>Headlines</h3>
          {headlines.map((row, i) => (
            <div key={i} style={{ padding: "12px 0", borderBottom: "1px solid #1d2330" }}>
              <strong style={{ color: "#60a5fa" }}>{row.title}</strong>
              <div style={{ color: "#94a0b4", marginTop: 4 }}>{row.summary}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
