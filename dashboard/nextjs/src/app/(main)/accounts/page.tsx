"use client";

import { accountsMock } from "@/lib/mock/accounts";

/* ---- Status Pill ---- */
function StatusPill({ label, color }: { label: string; color: string }) {
  const c =
    color === "green"
      ? "#32D583"
      : color === "orange"
        ? "#ffd740"
        : "#A5ADBA";
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

export default function AccountsPage() {
  const cards = accountsMock.cards;
  const accounts = accountsMock.items;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Summary Cards */}
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

      {/* Accounts Table */}
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
          Linked Accounts
        </h3>
        <div style={{ overflow: "hidden", borderRadius: 10 }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                {[
                  "Name",
                  "Type",
                  "Balance",
                  "Equity",
                  "Daily DD",
                  "Max DD",
                  "Rules",
                  "Status",
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
              {accounts.map((a) => (
                <tr key={a.id}>
                  <td
                    style={{
                      padding: "10px 10px",
                      borderBottom: "1px solid #30343C",
                      fontWeight: 700,
                      color: "#F5F7FA",
                    }}
                  >
                    {a.name}
                  </td>
                  <td
                    style={{
                      padding: "10px 10px",
                      borderBottom: "1px solid #30343C",
                      color: "#A5ADBA",
                    }}
                  >
                    {a.type}
                  </td>
                  <td
                    style={{
                      padding: "10px 10px",
                      borderBottom: "1px solid #30343C",
                      color: "#F5F7FA",
                      fontFamily: "monospace",
                    }}
                  >
                    {a.balance}
                  </td>
                  <td
                    style={{
                      padding: "10px 10px",
                      borderBottom: "1px solid #30343C",
                      color: "#F5F7FA",
                      fontFamily: "monospace",
                    }}
                  >
                    {a.equity}
                  </td>
                  <td
                    style={{
                      padding: "10px 10px",
                      borderBottom: "1px solid #30343C",
                      color: "#FF4D4F",
                      fontWeight: 700,
                    }}
                  >
                    {a.dailyDd}
                  </td>
                  <td
                    style={{
                      padding: "10px 10px",
                      borderBottom: "1px solid #30343C",
                      color: "#A5ADBA",
                    }}
                  >
                    {a.maxDd}
                  </td>
                  <td
                    style={{
                      padding: "10px 10px",
                      borderBottom: "1px solid #30343C",
                      color: "#717886",
                    }}
                  >
                    {a.rules}
                  </td>
                  <td
                    style={{
                      padding: "10px 10px",
                      borderBottom: "1px solid #30343C",
                    }}
                  >
                    <StatusPill label={a.status} color={a.statusColor} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Account Selector Cards */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 12,
        }}
      >
        {accounts.map((a) => {
          const borderColor =
            a.statusColor === "green" ? "#32D583" : "#ffd740";
          return (
            <div
              key={a.id}
              style={{
                background: "#23262C",
                border: `1px solid ${borderColor}40`,
                borderRadius: 14,
                padding: 16,
                cursor: "pointer",
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: 8,
                }}
              >
                <span
                  style={{ fontWeight: 700, fontSize: 15, color: "#F5F7FA" }}
                >
                  {a.name}
                </span>
                <StatusPill label={a.status} color={a.statusColor} />
              </div>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: 6,
                  fontSize: 13,
                }}
              >
                <span style={{ color: "#717886" }}>Balance</span>
                <span style={{ color: "#F5F7FA", textAlign: "right" }}>
                  {a.balance}
                </span>
                <span style={{ color: "#717886" }}>Equity</span>
                <span style={{ color: "#F5F7FA", textAlign: "right" }}>
                  {a.equity}
                </span>
                <span style={{ color: "#717886" }}>Daily DD</span>
                <span
                  style={{
                    color: "#FF4D4F",
                    textAlign: "right",
                    fontWeight: 700,
                  }}
                >
                  {a.dailyDd}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
