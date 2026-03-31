"use client";

/* ─── Dashboard Home — matching HTML prototype stats view ── */

function StatCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div
      style={{
        background: "#1A1C1F",
        border: "1px solid #2E333B",
        borderRadius: 14,
        padding: 16,
      }}
    >
      <div style={{ color: "#A4ACB9", fontSize: 12, textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 800, marginTop: 8, color: color ?? "#F5F7FA" }}>{value}</div>
    </div>
  );
}

function ChartPlaceholder({ title }: { title: string }) {
  return (
    <div
      style={{
        background: "#1A1C1F",
        border: "1px solid #2E333B",
        borderRadius: 14,
        padding: 16,
      }}
    >
      <h3 style={{ margin: "0 0 12px", fontSize: 18, fontWeight: 700 }}>{title}</h3>
      <div
        style={{
          height: 320,
          borderRadius: 14,
          border: "1px solid #2E333B",
          background:
            "linear-gradient(to right, transparent 0 9.5%, rgba(255,255,255,.05) 9.5% 10%), linear-gradient(to bottom, transparent 0 19.5%, rgba(255,255,255,.05) 19.5% 20%)",
          backgroundSize: "10% 100%, 100% 20%",
          backgroundColor: "#0A0B0D",
          position: "relative",
          overflow: "hidden",
        }}
      >
        <svg
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          style={{ position: "absolute", inset: 20, width: "calc(100% - 40px)", height: "calc(100% - 40px)" }}
        >
          <polyline
            fill="none"
            stroke="#C7FF1A"
            strokeWidth="0.5"
            points="0,45 5,54 10,49 15,60 20,55 25,58 30,53 35,48 40,50 45,43 50,38 55,40 60,34 65,30 70,28 75,36 80,32 85,29 90,35 95,40 100,37"
          />
          <polyline
            fill="none"
            stroke="#14b8a6"
            strokeWidth="0.3"
            points="0,55 5,56 10,57 15,56 20,55 25,54 30,53 35,52 40,50 45,49 50,47 55,45 60,42 65,39 70,37 75,36 80,35 85,35 90,36 95,37 100,38"
          />
        </svg>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* KPI Stats */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 12,
        }}
      >
        <StatCard label="Net P&L" value="$2,430" color="#22c55e" />
        <StatCard label="Win Rate" value="58%" />
        <StatCard label="Avg R:R" value="1.9" />
        <StatCard label="Profit Factor" value="1.47" />
      </div>

      {/* Charts */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1.2fr 0.8fr",
          gap: 14,
        }}
      >
        <ChartPlaceholder title="Performance by Hour" />
        <ChartPlaceholder title="Gross Daily P&L" />
      </div>

      {/* Utility cards */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 14,
        }}
      >
        {[
          { title: "TradeLocker", desc: "Desktop Terminal" },
          { title: "MatchTrader", desc: "Mobile iPhone" },
          { title: "cTrader", desc: "Web Terminal" },
          { title: "MT5", desc: "Web Terminal" },
          { title: "Journal Tool", desc: "My Trading Journey" },
          { title: "Account Sync", desc: "Manual / EA bridge" },
        ].map((card) => (
          <div
            key={card.title}
            style={{
              background: "#1A1C1F",
              border: "1px solid #2E333B",
              borderRadius: 14,
              padding: 16,
              minHeight: 130,
            }}
          >
            <h4 style={{ margin: "0 0 10px", fontWeight: 700 }}>{card.title}</h4>
            <div style={{ color: "#A4ACB9" }}>{card.desc}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
