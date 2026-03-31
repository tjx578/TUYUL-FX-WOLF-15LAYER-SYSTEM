"use client";

import { useCallback, useMemo, useState } from "react";
import { TabPanel, Tabs, type TabItem } from "@/components/ui/Tabs";
import { NewsScreen } from "@/features/news/components/NewsScreen";
import { useLivePrices } from "@/lib/realtime/hooks/useLivePrices";

/* ─── Tab definitions ─────────────────────────────────────── */

const MAIN_TABS: TabItem[] = [
  { id: "chart", label: "CHART" },
  { id: "lot", label: "LOT CALCULATOR" },
  { id: "news", label: "NEWS" },
  { id: "watchlist", label: "WATCHLIST" },
];

const SUB_TABS: TabItem[] = [
  { id: "calendar", label: "ECONOMIC CALENDAR" },
  { id: "heatmap", label: "FOREX HEATMAP" },
  { id: "cross", label: "CROSS RATES" },
];

/* ─── TradingView embed ──────────────────────────────────── */

function TradingViewFrame({ src, title, height = 560 }: { src: string; title: string; height?: number }) {
  return (
    <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
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

/* ─── Watchlist (live prices) ────────────────────────────── */

function WatchlistTab() {
  const { priceMap } = useLivePrices();
  const rows = Object.entries(priceMap ?? {});

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4">
        <p className="font-mono text-[11px] tracking-[0.12em] text-[var(--text-dim)]">LIVE WATCHLIST</p>
        <p className="mt-1 text-sm text-[var(--text-muted)]">
          Real-time prices streamed from websocket live hooks.
        </p>
      </div>

      <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
        <table className="w-full text-sm">
          <thead className="border-b border-[var(--border)] bg-[var(--bg-elevated)] text-left font-mono text-xs text-[var(--text-dim)]">
            <tr>
              <th className="px-4 py-3">PAIR</th>
              <th className="px-4 py-3">BID</th>
              <th className="px-4 py-3">ASK</th>
              <th className="px-4 py-3">SPREAD</th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 20).map(([symbol, tick]) => {
              const bid = Number(tick.bid ?? 0);
              const ask = Number(tick.ask ?? 0);
              const spread = ask > 0 && bid > 0 ? (ask - bid).toFixed(5) : "-";
              return (
                <tr key={symbol} className="border-b border-[var(--border)]/70 last:border-0">
                  <td className="px-4 py-3 font-mono">{symbol}</td>
                  <td className="px-4 py-3">{bid > 0 ? bid.toFixed(5) : "-"}</td>
                  <td className="px-4 py-3">{ask > 0 ? ask.toFixed(5) : "-"}</td>
                  <td className="px-4 py-3 text-[var(--text-muted)]">{spread}</td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-[var(--text-muted)]">
                  Waiting for live ticks...
                </td>
              </tr>
            )}
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
  const [mainTab, setMainTab] = useState("chart");
  const [subTab, setSubTab] = useState("heatmap");

  const activeView = mainTab !== "" ? mainTab : subTab;

  const handleMainTab = useCallback((id: string) => { setMainTab(id); setSubTab(""); }, []);
  const handleSubTab = useCallback((id: string) => { setSubTab(id); setMainTab(""); }, []);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Market</h1>
        <p className="font-mono text-xs text-[var(--text-muted)]">
          Chart, calculator, news, calendar, heatmap, and cross rates.
        </p>
      </div>

      {/* Primary tabs */}
      <Tabs tabs={MAIN_TABS} activeTab={mainTab} onTabChange={handleMainTab}>
        <></>
      </Tabs>

      {/* Secondary tabs */}
      <Tabs tabs={SUB_TABS} activeTab={subTab} onTabChange={handleSubTab}>
        <></>
      </Tabs>

      {/* Content panels */}
      <div className="min-h-[500px]">
        {activeView === "chart" && (
          <TradingViewFrame
            title="TradingView Chart"
            src="https://s.tradingview.com/widgetembed/?symbol=OANDA:EURUSD&interval=60&theme=dark&style=1&timezone=Etc%2FUTC"
          />
        )}
        {activeView === "lot" && <LotCalculatorTab />}
        {activeView === "news" && <NewsScreen />}
        {activeView === "watchlist" && <WatchlistTab />}
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
