"use client";

import { useAccountsData } from "@/hooks/useAccountsData";
import { SummaryCards } from "@/components/shared/SummaryCards";

const STATUS_COLOR: Record<string, string> = {
  green: "#22c55e",
  orange: "#f59e0b",
  red: "#ef4444",
};

export function AccountsPage() {
  const { cards, items } = useAccountsData();

  return (
    <section>
      <SummaryCards items={cards} />

      <div style={{ overflow: "hidden", borderRadius: 12 }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              {["Account", "Type", "Balance", "Equity", "Daily DD", "Max DD", "Rules", "Status"].map((h) => (
                <th
                  key={h}
                  style={{
                    padding: "12px 10px",
                    borderBottom: "1px solid #1d2330",
                    textAlign: "left",
                    color: "#95a0b0",
                    fontSize: 12,
                    textTransform: "uppercase",
                    letterSpacing: "0.06em",
                    background: "#0c1016",
                  }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((row) => (
              <tr key={row.id}>
                <td style={{ padding: "12px 10px", borderBottom: "1px solid #1d2330", fontWeight: 700 }}>{row.name}</td>
                <td style={{ padding: "12px 10px", borderBottom: "1px solid #1d2330" }}>{row.type}</td>
                <td style={{ padding: "12px 10px", borderBottom: "1px solid #1d2330" }}>{row.balance}</td>
                <td style={{ padding: "12px 10px", borderBottom: "1px solid #1d2330" }}>{row.equity}</td>
                <td style={{ padding: "12px 10px", borderBottom: "1px solid #1d2330" }}>{row.dailyDd}</td>
                <td style={{ padding: "12px 10px", borderBottom: "1px solid #1d2330" }}>{row.maxDd}</td>
                <td style={{ padding: "12px 10px", borderBottom: "1px solid #1d2330" }}>{row.rules}</td>
                <td style={{ padding: "12px 10px", borderBottom: "1px solid #1d2330", color: STATUS_COLOR[row.statusColor] ?? "#e8eaed", fontWeight: 700 }}>
                  {row.status}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
