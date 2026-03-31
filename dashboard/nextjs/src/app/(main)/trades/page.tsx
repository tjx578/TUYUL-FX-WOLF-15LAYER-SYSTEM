"use client";

import { tradesMock } from "@/lib/mock/trades";

/* ---- Status Pill ---- */
const STATUS_MAP: Record<string, string> = {
  green: "#32D583",
  orange: "#ffd740",
  red: "#FF4D4F",
};

function StatusPill({ label, color }: { label: string; color: string }) {
  const c = STATUS_MAP[color] ?? "#A5ADBA";
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
      {label}
    </span>
  );
}

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

export default function TradesPage() {
  const cards = tradesMock.cards;
  const trades = tradesMock.items;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* KPI Strip */}
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

      {/* Active Trades Table */}
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
          Active Trades
        </h3>
        <div style={{ overflow: "hidden", borderRadius: 10 }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                {[
                  "Trade",
                  "Account",
                  "Status",
                  "Entry",
                  "Current",
                  "P&L",
                  "Duration",
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
              {trades.map((t) => (
                <tr key={t.id}>
                  <td
                    style={{
                      padding: "10px 10px",
                      borderBottom: "1px solid #30343C",
                      fontWeight: 700,
                      color: "#F5F7FA",
                    }}
                  >
                    {t.trade}
                  </td>
                  <td
                    style={{
                      padding: "10px 10px",
                      borderBottom: "1px solid #30343C",
                      color: "#A5ADBA",
                    }}
                  >
                    {t.account}
                  </td>
                  <td
                    style={{
                      padding: "10px 10px",
                      borderBottom: "1px solid #30343C",
                    }}
                  >
                    <StatusPill label={t.status} color={t.statusColor} />
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
                    {t.entry}
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
                    {t.current}
                  </td>
                  <td
                    style={{
                      padding: "10px 10px",
                      borderBottom: "1px solid #30343C",
                      fontWeight: 700,
                      color: t.pnl.startsWith("+")
                        ? "#32D583"
                        : "#FF4D4F",
                    }}
                  >
                    {t.pnl}
                  </td>
                  <td
                    style={{
                      padding: "10px 10px",
                      borderBottom: "1px solid #30343C",
                      color: "#717886",
                      fontFamily: "monospace",
                      fontSize: 13,
                    }}
                  >
                    {t.duration}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
