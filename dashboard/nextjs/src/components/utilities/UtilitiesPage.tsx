"use client";

import { useUtilitiesData } from "@/hooks/useUtilitiesData";

export function UtilitiesPage() {
  const { items } = useUtilitiesData();

  return (
    <section>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
        {items.map((item) => (
          <div
            key={item.title}
            style={{
              background: "#1A1C1F",
              border: "1px solid #2E333B",
              borderRadius: 14,
              padding: 18,
              cursor: "pointer",
            }}
          >
            <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 6 }}>{item.title}</div>
            <div style={{ color: "#A4ACB9", fontSize: 13 }}>{item.desc}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
