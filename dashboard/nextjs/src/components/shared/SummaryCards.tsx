/* Reusable summary-card strip matching prototype .cards pattern */

const COLOR_MAP: Record<string, string> = {
  green: "#22c55e",
  red: "#ef4444",
  blue: "#60a5fa",
  orange: "#f59e0b",
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
            background: "#0b0f15",
            border: "1px solid #232834",
            borderRadius: 14,
            padding: 14,
          }}
        >
          <div style={{ color: "#94a0b4", fontSize: 12 }}>{item.label}</div>
          <div
            style={{
              fontSize: 26,
              fontWeight: 800,
              color: item.color ? (COLOR_MAP[item.color] ?? "#e8eaed") : "#e8eaed",
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
