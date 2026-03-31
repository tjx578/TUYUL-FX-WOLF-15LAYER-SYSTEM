"use client";

import { useCallback, useMemo, useState } from "react";
import { Tabs, type TabItem } from "@/components/ui/Tabs";

/* ─── Tab definitions (matching HTML prototype) ──────────── */

const MAIN_TABS: TabItem[] = [
  { id: "market", label: "Market Details" },
  { id: "chart", label: "Trading View Chart" },
  { id: "lot", label: "Lotsize Calculator" },
  { id: "news", label: "Market Headlines" },
];

const SUB_TABS: TabItem[] = [
  { id: "calendar", label: "Economic Calendar" },
  { id: "heatmap", label: "Forex Heatmap" },
  { id: "cross", label: "Forex Cross Rates" },
];

/* ─── TradingView embed ──────────────────────────────────── */

function TradingViewFrame({ src, title, height = 560 }: { src: string; title: string; height?: number }) {
  return (
    <div style={{ overflow: "hidden", borderRadius: 12, border: "1px solid #232834", background: "#0b0f15" }}>
      <iframe
        src={src}
        title={title}
        loading="lazy"
        allowFullScreen
        style={{ width: "100%", height, border: "none", display: "block" }}
      />
    </div>
  );
}

/* ─── Watchlist / Market Details (live prices, prototype style) ─── */

const MARKET_MOCK = [
  { ticker: "AUDCAD", price: "0.95738", chg: "-0.17%", neg: true, bid: "0.95658", ask: "0.95669", high: "0.96119", low: "0.95476", rating: "Sell" },
  { ticker: "AUDCHF", price: "0.54906", chg: "-0.12%", neg: true, bid: "0.54898", ask: "0.54909", high: "0.55078", low: "0.54751", rating: "Neutral" },
  { ticker: "AUDUSD", price: "0.69250", chg: "-0.32%", neg: true, bid: "0.69187", ask: "0.69191", high: "0.69569", low: "0.69015", rating: "Sell" },
  { ticker: "CADAUD", price: "1.0441", chg: "+0.19%", neg: false, bid: "1.0454", ask: "1.0454", high: "1.0471", low: "1.0402", rating: "Buy" },
  { ticker: "CADCHF", price: "0.57345", chg: "+0.04%", neg: false, bid: "0.57390", ask: "0.57398", high: "0.57400", low: "0.57225", rating: "Buy" },
  { ticker: "EURUSD", price: "1.08240", chg: "+0.12%", neg: false, bid: "1.08220", ask: "1.08260", high: "1.08500", low: "1.07910", rating: "Buy" },
  { ticker: "GBPUSD", price: "1.26610", chg: "-0.05%", neg: true, bid: "1.26590", ask: "1.26630", high: "1.26890", low: "1.26310", rating: "Neutral" },
  { ticker: "USDJPY", price: "151.920", chg: "+0.19%", neg: false, bid: "151.900", ask: "151.940", high: "152.300", low: "151.500", rating: "Buy" },
];

function MarketDetailsView() {
  const ratingColor = (r: string) =>
    r === "Buy" ? "#60a5fa" : r === "Sell" ? "#ef4444" : "#9ca3af";

  return (
    <div>
      {/* Ticker strip */}
      <div
        style={{
          display: "flex",
          gap: 18,
          overflow: "auto",
          paddingBottom: 8,
          borderBottom: "1px solid #232834",
          marginBottom: 14,
        }}
      >
        {["BTC -2.66%", "ETH -4.44%", "S&P500 -0.38%", "US100 -0.68%"].map((t) => {
          const neg = t.includes("-");
          return (
            <div key={t} style={{ whiteSpace: "nowrap", color: "#d6dae3", fontWeight: 700 }}>
              {t.split(" ")[0]}{" "}
              <span style={{ color: neg ? "#ef4444" : "#14b8a6" }}>{t.split(" ")[1]}</span>
            </div>
          );
        })}
      </div>

      {/* Toolbar */}
      <div style={{ display: "flex", justifyContent: "space-between", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
        <div style={{ display: "flex", gap: 8 }}>
          <button style={{ background: "#0e1218", color: "#e8eaed", border: "1px solid #232834", borderRadius: 10, padding: "9px 12px", cursor: "pointer" }}>Overview</button>
          <button style={{ background: "#0e1218", color: "#e8eaed", border: "1px solid #232834", borderRadius: 10, padding: "9px 12px", cursor: "pointer" }}>Major / Minor Pairs</button>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <select style={{ background: "#0e1218", color: "#e8eaed", border: "1px solid #232834", borderRadius: 10, padding: "9px 12px" }}>
            <option>General</option>
          </select>
          <button style={{ background: "#0e1218", color: "#e8eaed", border: "1px solid #232834", borderRadius: 10, padding: "9px 12px", cursor: "pointer" }}>Filters</button>
        </div>
      </div>

      {/* Table */}
      <table style={{ width: "100%", borderCollapse: "collapse", borderRadius: 12, overflow: "hidden" }}>
        <thead>
          <tr>
            {["Ticker", "Price", "Chg %", "Bid", "Ask", "High", "Low", "Technical"].map((h) => (
              <th key={h} style={{ padding: "12px 10px", borderBottom: "1px solid #1d2330", textAlign: "left", color: "#95a0b0", fontSize: 12, textTransform: "uppercase", letterSpacing: "0.06em", background: "#0c1016" }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {MARKET_MOCK.map((row) => (
            <tr key={row.ticker}>
              <td style={{ padding: "12px 10px", borderBottom: "1px solid #1d2330" }}>{row.ticker}</td>
              <td style={{ padding: "12px 10px", borderBottom: "1px solid #1d2330" }}>{row.price}</td>
              <td style={{ padding: "12px 10px", borderBottom: "1px solid #1d2330", color: row.neg ? "#ef4444" : "#14b8a6" }}>{row.chg}</td>
              <td style={{ padding: "12px 10px", borderBottom: "1px solid #1d2330" }}>{row.bid}</td>
              <td style={{ padding: "12px 10px", borderBottom: "1px solid #1d2330" }}>{row.ask}</td>
              <td style={{ padding: "12px 10px", borderBottom: "1px solid #1d2330" }}>{row.high}</td>
              <td style={{ padding: "12px 10px", borderBottom: "1px solid #1d2330" }}>{row.low}</td>
              <td style={{ padding: "12px 10px", borderBottom: "1px solid #1d2330", color: ratingColor(row.rating), fontWeight: 700 }}>
                {row.rating}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ─── News view (matching prototype 2-col layout) ────────── */

function NewsView() {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1.2fr 0.8fr", gap: 14 }}>
      <div style={{ background: "#0b0f15", border: "1px solid #232834", borderRadius: 14, padding: 14 }}>
        <h3 style={{ margin: "0 0 12px", fontSize: 18, fontWeight: 700 }}>Top Stories</h3>
        {[
          { pair: "GBP/USD", text: "Pound ticks up as UK inflation lands steady at 3% in February." },
          { pair: "USD/JPY", text: "Dollar chases ¥160.00 as FX markets reshuffle amid war jitters." },
          { pair: "EUR/USD", text: "Euro tumbles as traders flock to greenback support levels." },
          { pair: "USD/JPY", text: "Dollar pops above ¥153 after Japan's economy barely avoids recession." },
        ].map((h, i) => (
          <div key={i} style={{ padding: "12px 0", borderBottom: "1px solid #1d2330" }}>
            <strong>{h.pair}:</strong> {h.text}
          </div>
        ))}
      </div>
      <div style={{ background: "#0b0f15", border: "1px solid #232834", borderRadius: 14, padding: 14 }}>
        <h3 style={{ margin: "0 0 12px", fontSize: 18, fontWeight: 700 }}>News Lock</h3>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <tbody>
            {[
              ["High impact", "Enabled"],
              ["Lock before", "30 min"],
              ["Lock after", "30 min"],
            ].map(([k, v]) => (
              <tr key={k}><td style={{ padding: "12px 10px", borderBottom: "1px solid #1d2330" }}>{k}</td><td style={{ padding: "12px 10px", borderBottom: "1px solid #1d2330" }}>{v}</td></tr>
            ))}
            <tr>
              <td style={{ padding: "12px 10px", borderBottom: "1px solid #1d2330" }}>Status</td>
              <td style={{ padding: "12px 10px", borderBottom: "1px solid #1d2330", color: "#ef4444", fontWeight: 700 }}>New trades blocked during window</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ─── Lot Size Calculator ────────────────────────────────── */

const PAIR_PIP_VALUES: Record<string, number> = {
  EURUSD: 10, GBPUSD: 10, AUDUSD: 10, NZDUSD: 10,
  USDCHF: 10.15, USDCAD: 7.35, USDJPY: 6.62,
  GBPJPY: 6.62, EURJPY: 6.62, EURGBP: 12.56,
};

function LotCalculatorTab() {
  const [pair, setPair] = useState("EURUSD");
  const [entry, setEntry] = useState("1.08240");
  const [sl, setSl] = useState("1.07910");
  const [riskPct, setRiskPct] = useState("0.50");
  const [balance, setBalance] = useState("50000");
  const [rrTarget, setRrTarget] = useState("2.5");

  const calc = useMemo(() => {
    const bal = parseFloat(balance) || 0;
    const risk = parseFloat(riskPct) || 0;
    const entryP = parseFloat(entry) || 0;
    const slP = parseFloat(sl) || 0;
    const rr = parseFloat(rrTarget) || 0;

    const riskAmount = bal * (risk / 100);
    const slPips = Math.abs(entryP - slP) / (pair.includes("JPY") ? 0.01 : 0.0001);
    const pipValue = PAIR_PIP_VALUES[pair] ?? 10;
    const lotSize = slPips > 0 ? riskAmount / (slPips * pipValue) : 0;
    const tpDistance = Math.abs(entryP - slP) * rr;
    const direction = entryP > slP ? "BUY" : "SELL";
    const tp = direction === "BUY" ? entryP + tpDistance : entryP - tpDistance;

    return { riskAmount, slPips, lotSize, tp, direction };
  }, [pair, entry, sl, riskPct, balance, rrTarget]);

  const inputCls = "w-full rounded-lg border border-[var(--border)] bg-[#0e1218] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]";
  const labelCls = "block text-xs font-mono tracking-wider text-[var(--text-muted)] mb-1";

  return (
    <div className="grid gap-4 lg:grid-columns-2" style={{ display: "grid", gridTemplateColumns: "1.2fr 0.8fr", gap: 16 }}>
      {/* Left: Input form */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-5 space-y-4">
        <h3 className="text-base font-bold">Position Calculator</h3>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>PAIR</label>
            <select value={pair} onChange={(e) => setPair(e.target.value)} className={inputCls}>
              {Object.keys(PAIR_PIP_VALUES).map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div>
            <label className={labelCls}>BALANCE ($)</label>
            <input type="number" value={balance} onChange={(e) => setBalance(e.target.value)} className={inputCls} />
          </div>
          <div>
            <label className={labelCls}>ENTRY PRICE</label>
            <input type="text" value={entry} onChange={(e) => setEntry(e.target.value)} className={inputCls} />
          </div>
          <div>
            <label className={labelCls}>STOP LOSS</label>
            <input type="text" value={sl} onChange={(e) => setSl(e.target.value)} className={inputCls} />
          </div>
          <div>
            <label className={labelCls}>RISK %</label>
            <input type="number" step="0.1" value={riskPct} onChange={(e) => setRiskPct(e.target.value)} className={inputCls} />
          </div>
          <div>
            <label className={labelCls}>R:R TARGET</label>
            <input type="number" step="0.1" value={rrTarget} onChange={(e) => setRrTarget(e.target.value)} className={inputCls} />
          </div>
        </div>
      </div>

      {/* Right: Result */}
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-xl border border-[var(--border)] bg-[#171c25] p-4">
            <div className="text-xs text-[var(--text-muted)] uppercase font-mono">Lot Size</div>
            <div className="mt-2 text-2xl font-extrabold">{calc.lotSize.toFixed(2)}</div>
          </div>
          <div className="rounded-xl border border-[var(--border)] bg-[#171c25] p-4">
            <div className="text-xs text-[var(--text-muted)] uppercase font-mono">Risk Amount</div>
            <div className="mt-2 text-2xl font-extrabold">${calc.riskAmount.toFixed(0)}</div>
          </div>
          <div className="rounded-xl border border-[var(--border)] bg-[#171c25] p-4">
            <div className="text-xs text-[var(--text-muted)] uppercase font-mono">SL Pips</div>
            <div className="mt-2 text-2xl font-extrabold">{calc.slPips.toFixed(1)}</div>
          </div>
          <div className="rounded-xl border border-[var(--border)] bg-[#171c25] p-4">
            <div className="text-xs text-[var(--text-muted)] uppercase font-mono">Direction</div>
            <div className={`mt-2 text-2xl font-extrabold ${calc.direction === "BUY" ? "text-[#22c55e]" : "text-[#ef4444]"}`}>{calc.direction}</div>
          </div>
        </div>

        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4">
          <h3 className="mb-3 text-sm font-bold">Formula</h3>
          <p className="mb-3 text-xs text-[var(--text-muted)]">Lot = Risk Amount ÷ (SL pips × pip value)</p>
          <table className="w-full text-sm">
            <tbody>
              <tr className="border-b border-[var(--border)]"><td className="py-2 text-[var(--text-muted)]">Pair</td><td className="py-2 font-mono">{pair}</td></tr>
              <tr className="border-b border-[var(--border)]"><td className="py-2 text-[var(--text-muted)]">Entry</td><td className="py-2 font-mono">{entry}</td></tr>
              <tr className="border-b border-[var(--border)]"><td className="py-2 text-[var(--text-muted)]">SL</td><td className="py-2 font-mono">{sl}</td></tr>
              <tr className="border-b border-[var(--border)]"><td className="py-2 text-[var(--text-muted)]">TP</td><td className="py-2 font-mono">{calc.tp.toFixed(5)}</td></tr>
              <tr><td className="py-2 text-[var(--text-muted)]">R:R</td><td className="py-2 font-mono">1 : {rrTarget}</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

/* ─── Forex Heatmap ──────────────────────────────────────── */

const CURRENCIES = ["EUR", "USD", "JPY", "GBP", "CHF", "AUD"] as const;

const HEATMAP_DATA: Record<string, Record<string, number | null>> = {
  EUR: { EUR: null, USD: -0.08, JPY: 0.01, GBP: -0.08, CHF: 0.08, AUD: 0.25 },
  USD: { EUR: 0.07, USD: null, JPY: 0.10, GBP: -0.02, CHF: 0.20, AUD: 0.36 },
  JPY: { EUR: 0.04, USD: -0.08, JPY: null, GBP: -0.02, CHF: 0.04, AUD: 0.27 },
  GBP: { EUR: 0.16, USD: 0.04, JPY: 0.11, GBP: null, CHF: 0.18, AUD: 0.39 },
  CHF: { EUR: -0.09, USD: -0.18, JPY: -0.06, GBP: -0.17, CHF: null, AUD: 0.15 },
  AUD: { EUR: -0.24, USD: -0.32, JPY: -0.26, GBP: -0.38, CHF: -0.12, AUD: null },
};

function heatColor(val: number | null): string {
  if (val === null) return "bg-[#222]";
  if (val > 0.15) return "bg-[rgba(20,184,166,0.35)]";
  if (val > 0) return "bg-[rgba(20,184,166,0.18)]";
  if (val < -0.15) return "bg-[rgba(239,68,68,0.35)]";
  if (val < 0) return "bg-[rgba(239,68,68,0.18)]";
  return "bg-[#222]";
}

function HeatmapTab() {
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4">
        <p className="font-mono text-[11px] tracking-[0.12em] text-[var(--text-dim)]">FOREX HEATMAP</p>
        <p className="mt-1 text-sm text-[var(--text-muted)]">
          Currency strength matrix — percentage change relative to each cross.
        </p>
      </div>

      <div className="overflow-hidden rounded-xl border border-[var(--border)]" style={{ display: "grid", gridTemplateColumns: `120px repeat(${CURRENCIES.length}, 1fr)` }}>
        {/* Header row */}
        <div className="bg-[#0d1118] p-4 text-center font-bold border-r border-b border-[#1b2130]" />
        {CURRENCIES.map((c) => (
          <div key={`h-${c}`} className="bg-[#0d1118] p-4 text-center font-bold border-r border-b border-[#1b2130]">{c}</div>
        ))}

        {/* Data rows */}
        {CURRENCIES.map((row) => (
          <>
            <div key={`r-${row}`} className="bg-[#0d1118] p-4 text-center font-bold border-r border-b border-[#1b2130]">{row}</div>
            {CURRENCIES.map((col) => {
              const val = HEATMAP_DATA[row]?.[col] ?? null;
              return (
                <div
                  key={`${row}-${col}`}
                  className={`p-4 text-center text-sm font-medium border-r border-b border-[#1b2130] ${heatColor(val)}`}
                >
                  {val === null ? "—" : `${val > 0 ? "+" : ""}${val.toFixed(2)}%`}
                </div>
              );
            })}
          </>
        ))}
      </div>
    </div>
  );
}

/* ─── Cross Rates ────────────────────────────────────────── */

interface CrossRate {
  pair: string;
  last: string;
  h1: { val: string; pos: boolean };
  h4: { val: string; pos: boolean };
  d1: { val: string; pos: boolean };
  bias: { label: string; cls: string };
}

const CROSS_DATA: CrossRate[] = [
  { pair: "EURUSD", last: "1.0824", h1: { val: "+0.12%", pos: true }, h4: { val: "-0.08%", pos: false }, d1: { val: "+0.31%", pos: true }, bias: { label: "Bullish", cls: "text-[#60a5fa]" } },
  { pair: "GBPUSD", last: "1.2661", h1: { val: "-0.05%", pos: false }, h4: { val: "+0.14%", pos: true }, d1: { val: "+0.22%", pos: true }, bias: { label: "Bullish", cls: "text-[#60a5fa]" } },
  { pair: "USDJPY", last: "151.92", h1: { val: "+0.19%", pos: true }, h4: { val: "+0.41%", pos: true }, d1: { val: "-0.12%", pos: false }, bias: { label: "Mixed", cls: "text-[#9ca3af]" } },
  { pair: "AUDUSD", last: "0.6925", h1: { val: "-0.32%", pos: false }, h4: { val: "-0.18%", pos: false }, d1: { val: "+0.05%", pos: true }, bias: { label: "Bearish", cls: "text-[#ef4444]" } },
  { pair: "USDCAD", last: "1.3562", h1: { val: "+0.08%", pos: true }, h4: { val: "+0.22%", pos: true }, d1: { val: "-0.11%", pos: false }, bias: { label: "Bullish", cls: "text-[#60a5fa]" } },
  { pair: "USDCHF", last: "0.8834", h1: { val: "+0.04%", pos: true }, h4: { val: "-0.06%", pos: false }, d1: { val: "+0.14%", pos: true }, bias: { label: "Mixed", cls: "text-[#9ca3af]" } },
  { pair: "NZDUSD", last: "0.5681", h1: { val: "-0.21%", pos: false }, h4: { val: "-0.14%", pos: false }, d1: { val: "-0.29%", pos: false }, bias: { label: "Bearish", cls: "text-[#ef4444]" } },
  { pair: "EURGBP", last: "0.8549", h1: { val: "+0.06%", pos: true }, h4: { val: "-0.03%", pos: false }, d1: { val: "+0.09%", pos: true }, bias: { label: "Mixed", cls: "text-[#9ca3af]" } },
  { pair: "EURJPY", last: "164.43", h1: { val: "+0.28%", pos: true }, h4: { val: "+0.35%", pos: true }, d1: { val: "+0.19%", pos: true }, bias: { label: "Bullish", cls: "text-[#60a5fa]" } },
  { pair: "GBPJPY", last: "192.32", h1: { val: "+0.14%", pos: true }, h4: { val: "+0.52%", pos: true }, d1: { val: "+0.09%", pos: true }, bias: { label: "Bullish", cls: "text-[#60a5fa]" } },
];

function CrossRatesTab() {
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4">
        <p className="font-mono text-[11px] tracking-[0.12em] text-[var(--text-dim)]">FOREX CROSS RATES</p>
        <p className="mt-1 text-sm text-[var(--text-muted)]">
          Multi-timeframe change and directional bias for major and cross pairs.
        </p>
      </div>

      <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
        <table className="w-full text-sm">
          <thead className="border-b border-[var(--border)] bg-[var(--bg-elevated)] text-left font-mono text-xs text-[var(--text-dim)]">
            <tr>
              <th className="px-4 py-3">PAIR</th>
              <th className="px-4 py-3">LAST</th>
              <th className="px-4 py-3">1H</th>
              <th className="px-4 py-3">4H</th>
              <th className="px-4 py-3">D1</th>
              <th className="px-4 py-3">BIAS</th>
            </tr>
          </thead>
          <tbody>
            {CROSS_DATA.map((r) => (
              <tr key={r.pair} className="border-b border-[var(--border)]/70 last:border-0 hover:bg-[#0c1118]">
                <td className="px-4 py-3 font-mono font-bold">{r.pair}</td>
                <td className="px-4 py-3">{r.last}</td>
                <td className={`px-4 py-3 ${r.h1.pos ? "text-[#14b8a6]" : "text-[#ef4444]"}`}>{r.h1.val}</td>
                <td className={`px-4 py-3 ${r.h4.pos ? "text-[#14b8a6]" : "text-[#ef4444]"}`}>{r.h4.val}</td>
                <td className={`px-4 py-3 ${r.d1.pos ? "text-[#14b8a6]" : "text-[#ef4444]"}`}>{r.d1.val}</td>
                <td className={`px-4 py-3 font-bold ${r.bias.cls}`}>{r.bias.label}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ─── Page ───────────────────────────────────────────────── */

export default function MarketPage() {
  const [mainTab, setMainTab] = useState("market");
  const [subTab, setSubTab] = useState("");

  const activeView = mainTab !== "" ? mainTab : subTab;

  const handleMainTab = useCallback((id: string) => { setMainTab(id); setSubTab(""); }, []);
  const handleSubTab = useCallback((id: string) => { setSubTab(id); setMainTab(""); }, []);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Primary tabs */}
      <Tabs tabs={MAIN_TABS} activeTab={mainTab} onTabChange={handleMainTab} columns={4}>
        <></>
      </Tabs>

      {/* Secondary tabs */}
      <Tabs tabs={SUB_TABS} activeTab={subTab} onTabChange={handleSubTab} columns={3}>
        <></>
      </Tabs>

      {/* Content */}
      <div style={{ background: "#05070a", border: "1px solid #1a1f2b", borderRadius: 16, padding: 14, minHeight: 500 }}>
        {activeView === "market" && <MarketDetailsView />}
        {activeView === "chart" && (
          <TradingViewFrame
            title="TradingView Chart"
            src="https://s.tradingview.com/widgetembed/?symbol=OANDA:EURUSD&interval=60&theme=dark&style=1&timezone=Etc%2FUTC"
          />
        )}
        {activeView === "lot" && <LotCalculatorTab />}
        {activeView === "news" && <NewsView />}
        {activeView === "calendar" && (
          <TradingViewFrame
            title="Economic Calendar"
            src="https://s.tradingview.com/embed-widget/events/?locale=en&importance=0,1&colorTheme=dark&isTransparent=true"
            height={620}
          />
        )}
        {activeView === "heatmap" && <HeatmapTab />}
        {activeView === "cross" && <CrossRatesTab />}
      </div>
    </div>
  );
}
