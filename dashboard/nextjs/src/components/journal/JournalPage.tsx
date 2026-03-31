"use client";

import { useJournalData } from "@/hooks/useJournalData";

export function JournalPage() {
  const { entries, stats } = useJournalData();

  return (
    <section>
      <div style={{ display: "grid", gridTemplateColumns: "1.2fr 0.8fr", gap: 14 }}>
        {/* Recent entries */}
        <div style={{ background: "#1A1C1F", border: "1px solid #2E333B", borderRadius: 14, padding: 14 }}>
          <h3 style={{ margin: "0 0 12px", fontSize: 18, fontWeight: 700 }}>Recent Journal</h3>
          {entries.map((entry, i) => (
            <div key={i} style={{ padding: "12px 0", borderBottom: "1px solid #2E333B" }}>
              <strong style={{ color: "#F5F7FA" }}>{entry.title}</strong>
              <div style={{ color: "#A4ACB9", marginTop: 4 }}>{entry.note}</div>
            </div>
          ))}
        </div>

        {/* Stats */}
        <div style={{ background: "#1A1C1F", border: "1px solid #2E333B", borderRadius: 14, padding: 14 }}>
          <h3 style={{ margin: "0 0 12px", fontSize: 18, fontWeight: 700 }}>Stats</h3>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <tbody>
              {stats.map((s, i) => (
                <tr key={i}>
                  <td style={{ padding: "12px 10px", borderBottom: "1px solid #2E333B", color: "#A4ACB9" }}>{s.key}</td>
                  <td style={{ padding: "12px 10px", borderBottom: "1px solid #2E333B", fontWeight: 700 }}>{s.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
