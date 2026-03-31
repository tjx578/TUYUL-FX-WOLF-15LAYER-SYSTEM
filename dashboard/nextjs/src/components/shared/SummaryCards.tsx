/* Reusable summary-card strip — lime neon theme */

const COLOR_MAP: Record<string, string> = {
  green: "#22c55e",
  red: "#ef4444",
  blue: "#60a5fa",
  orange: "#f59e0b",
  lime: "#C7FF1A",
  gold: "#d8b35d",
};

export function SummaryCards({
  items,
}: {
  items: ReadonlyArray<{ label: string; value: string; color?: string }>;
}) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: `repeat(${items.length}, 1fr)`, gap: 12, marginBottom: 14 }}>
      {items.map((item) => (
        <div
          key={item.label}
          style={{
            background: "#1A1C1F",
            border: "1px solid #2E333B",
            borderRadius: 14,
            padding: 14,
          }}
        >
          <div style={{ color: "#A4ACB9", fontSize: 12 }}>{item.label}</div>
          <div
            style={{
              fontSize: 26,
              fontWeight: 800,
              color: item.color ? (COLOR_MAP[item.color] ?? "#F5F7FA") : "#F5F7FA",
              marginTop: 4,
            }}
          >
            {item.value}
          </div>
        </div>
      ))}
    </div>
  );
}
