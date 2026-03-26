"use client";

export function RiskStat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div>
      <div style={{ fontSize: 9, color: "var(--text-muted)", letterSpacing: "0.09em", marginBottom: 3 }}>
        {label}
      </div>
      <div className="num" style={{ fontSize: 15, fontWeight: 700, color: color ?? "var(--text-primary)" }}>
        {value}
      </div>
    </div>
  );
}
