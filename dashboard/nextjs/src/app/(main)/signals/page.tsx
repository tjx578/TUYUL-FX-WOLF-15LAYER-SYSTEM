"use client";

import { useState } from "react";
import { signalsMock } from "@/lib/mock/signals";

/* ---- Pills ---- */
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

/* ---- Summary Card ---- */
function SummaryCard({
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

/* ---- Tabs ---- */
const TAB_IDS = ["screener", "chart", "risk", "headlines"] as const;
const TAB_LABELS: Record<string, string> = {
  screener: "SIGNAL SCREENER",
  chart: "CHART VIEW",
  risk: "RISK PREVIEW",
  headlines: "HEADLINES",
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

export default function SignalsPage() {
  const [tab, setTab] = useState<string>("screener");
  const [sessionFilter, setSessionFilter] = useState("ALL");
  const signals = signalsMock.items;
  const cards = signalsMock.cards;

  const filtered =
    sessionFilter === "ALL"
      ? signals
      : signals.filter((s) => s.session === sessionFilter);

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
          <SummaryCard
            key={c.label}
            label={c.label}
            value={c.value}
            color={"color" in c ? c.color : undefined}
          />
        ))}
      </div>

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
              border: tab === t ? "1px solid #30343C" : "1px solid transparent",
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

      {/* Tab Content */}
      {tab === "screener" && (
        <div
          style={{
            background: "#0A0B0D",
            border: "1px solid #1B1D21",
            borderRadius: 16,
            padding: 14,
          }}
        >
          {/* Filter Bar */}
          <div
            style={{
              display: "flex",
              gap: 8,
              marginBottom: 14,
              flexWrap: "wrap",
            }}
          >
            {["ALL", "London", "New York"].map((s) => (
              <button
                key={s}
                onClick={() => setSessionFilter(s)}
                style={{
                  background:
                    sessionFilter === s ? "#C8FF1A" : "transparent",
                  color: sessionFilter === s ? "#0A0B0D" : "#A5ADBA",
                  border: `1px solid ${sessionFilter === s ? "#C8FF1A" : "#30343C"}`,
                  borderRadius: 999,
                  padding: "6px 16px",
                  fontSize: 11,
                  fontWeight: 700,
                  cursor: "pointer",
                  letterSpacing: "0.06em",
                }}
              >
                {s.toUpperCase()}
              </button>
            ))}
          </div>

          {/* Signal Table */}
          <div style={{ overflow: "hidden", borderRadius: 10 }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  {[
                    "Pair",
                    "Bias",
                    "Confidence",
                    "Session",
                    "Entry",
                    "SL",
                    "TP",
                    "R:R",
                    "Action",
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
                {filtered.map((s) => (
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
                        color:
                          s.confidence >= 80 ? "#32D583" : "#A5ADBA",
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
                        color: "#F5F7FA",
                        fontFamily: "monospace",
                        fontSize: 13,
                      }}
                    >
                      {s.entry}
                    </td>
                    <td
                      style={{
                        padding: "10px 10px",
                        borderBottom: "1px solid #30343C",
                        color: "#FF4D4F",
                        fontFamily: "monospace",
                        fontSize: 13,
                      }}
                    >
                      {s.sl}
                    </td>
                    <td
                      style={{
                        padding: "10px 10px",
                        borderBottom: "1px solid #30343C",
                        color: "#32D583",
                        fontFamily: "monospace",
                        fontSize: 13,
                      }}
                    >
                      {s.tp}
                    </td>
                    <td
                      style={{
                        padding: "10px 10px",
                        borderBottom: "1px solid #30343C",
                        color: "#C8FF1A",
                        fontWeight: 700,
                      }}
                    >
                      {s.rr}
                    </td>
                    <td
                      style={{
                        padding: "10px 10px",
                        borderBottom: "1px solid #30343C",
                      }}
                    >
                      <button
                        style={{
                          background: "#C8FF1A",
                          color: "#0A0B0D",
                          border: "none",
                          borderRadius: 8,
                          padding: "5px 14px",
                          cursor: "pointer",
                          fontSize: 11,
                          fontWeight: 800,
                        }}
                      >
                        TAKE
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "chart" && (
        <Placeholder
          title="CHART VIEW"
          desc="Multi-timeframe chart with signal overlay and entry zone markers."
        />
      )}
      {tab === "risk" && (
        <Placeholder
          title="RISK PREVIEW"
          desc="Pre-trade risk simulation: lot sizing, DD impact, and correlation check."
        />
      )}
      {tab === "headlines" && (
        <Placeholder
          title="HEADLINES"
          desc="Live news feed filtered by currency relevance and impact level."
        />
      )}
    </div>
  );
}
