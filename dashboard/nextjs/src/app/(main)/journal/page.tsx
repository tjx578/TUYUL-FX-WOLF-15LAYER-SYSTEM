"use client";

import { journalMock } from "@/lib/mock/journal";

export default function JournalPage() {
  const entries = journalMock.entries;
  const stats = journalMock.stats;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Stats Strip */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 12,
        }}
      >
        {stats.map((s) => (
          <div
            key={s.key}
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
              {s.key}
            </div>
            <div
              style={{
                fontSize: 26,
                fontWeight: 800,
                marginTop: 8,
                color: "#F5F7FA",
              }}
            >
              {s.value}
            </div>
          </div>
        ))}
      </div>

      {/* 2-Column: Timeline + Stats Table */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1.2fr 0.8fr",
          gap: 14,
        }}
      >
        {/* Timeline Cards */}
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
            Recent Entries
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {entries.map((e, i) => (
              <div
                key={i}
                style={{
                  background: "#23262C",
                  border: "1px solid #30343C",
                  borderRadius: 12,
                  padding: "14px 16px",
                  borderLeft: "3px solid #C8FF1A",
                }}
              >
                <div
                  style={{
                    fontWeight: 700,
                    fontSize: 14,
                    color: "#F5F7FA",
                    marginBottom: 6,
                  }}
                >
                  {e.title}
                </div>
                <div style={{ color: "#A5ADBA", fontSize: 13 }}>
                  {e.note}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Stats Table */}
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
            Performance Stats
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
            {stats.map((s, i) => (
              <div
                key={s.key}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  padding: "12px 0",
                  borderBottom:
                    i < stats.length - 1 ? "1px solid #30343C" : "none",
                }}
              >
                <span style={{ color: "#A5ADBA", fontSize: 14 }}>
                  {s.key}
                </span>
                <span
                  style={{
                    color: "#F5F7FA",
                    fontWeight: 700,
                    fontSize: 14,
                  }}
                >
                  {s.value}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
