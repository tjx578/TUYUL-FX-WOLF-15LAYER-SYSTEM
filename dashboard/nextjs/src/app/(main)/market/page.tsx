"use client";

import React, { useMemo, useState } from "react";
import { NewsScreen } from "@/features/news/components/NewsScreen";
import { useLivePrices } from "@/lib/realtime/hooks/useLivePrices";

const TABS = [
  { id: "chart", label: "CHART" },
  { id: "calendar", label: "CALENDAR" },
  { id: "news", label: "NEWS" },
  { id: "watchlist", label: "WATCHLIST" },
] as const;

type TabId = (typeof TABS)[number]["id"];

function tabStyle(active: boolean): React.CSSProperties {
  return {
    padding: "10px 20px",
    fontSize: 11,
    fontFamily: "var(--font-mono, monospace)",
    fontWeight: active ? 700 : 400,
    letterSpacing: "0.08em",
    color: active ? "var(--accent,#3b82f6)" : "var(--text-muted,#64748b)",
    background: "transparent",
    border: "none",
    borderBottom: active ? "2px solid var(--accent,#3b82f6)" : "2px solid transparent",
    marginBottom: -1,
    cursor: "pointer",
  };
}

function TradingViewWidget({ script, title }: { script: string; title: string }) {
  return <iframe srcDoc={script} style={{ width: "100%", height: 520, border: 0 }} title={title} />;
}

function chartEmbed(symbol = "FX:EURUSD") {
  return `<!doctype html><html><body style="margin:0;background:#0b1220;"><div class="tradingview-widget-container" style="height:100%;width:100%"><div id="tv_chart"></div><script src="https://s3.tradingview.com/tv.js"></script><script>new TradingView.widget({container_id:"tv_chart",symbol:"${symbol}",interval:"60",timezone:"Etc/UTC",theme:"dark",style:"1",locale:"en",allow_symbol_change:true,width:"100%",height:520});</script></div></body></html>`;
}

function eventsEmbed() {
  return `<!doctype html><html><body style="margin:0;background:#0b1220;"><div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div><script src="https://s3.tradingview.com/external-embedding/embed-widget-events.js">{"colorTheme":"dark","isTransparent":false,"width":"100%","height":520,"locale":"en","importanceFilter":"-1,0,1"}</script></div></body></html>`;
}

export default function MarketPage() {
  const [tab, setTab] = useState<TabId>("chart");
  const { data: prices = [] } = useLivePrices();
  const watch = useMemo(() => prices.slice(0, 14), [prices]);

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 18, fontWeight: 700, letterSpacing: "-0.01em", marginBottom: 4 }}>Market</h1>
        <p style={{ fontSize: 12, color: "var(--text-muted,#64748b)", fontFamily: "var(--font-mono, monospace)" }}>
          Chart · Calendar · News · Watchlist in one context
        </p>
      </div>

      <div style={{ display: "flex", borderBottom: "1px solid var(--border,#1e293b)", marginBottom: 24 }}>
        {TABS.map((t) => (
          <button key={t.id} style={tabStyle(tab === t.id)} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "chart" && <TradingViewWidget script={chartEmbed()} title="TradingView chart" />}
      {tab === "calendar" && <TradingViewWidget script={eventsEmbed()} title="TradingView calendar" />}
      {tab === "news" && <NewsScreen />}
      {tab === "watchlist" && (
        <div style={{ background: "var(--bg-card,#111827)", border: "1px solid var(--border,#1e293b)", borderRadius: 12, padding: 16 }}>
          <div style={{ marginBottom: 10, fontSize: 11, fontFamily: "var(--font-mono, monospace)", color: "var(--text-dim,#475569)" }}>LIVE PRICE WATCHLIST</div>
          {watch.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--text-muted,#64748b)" }}>Waiting for live prices...</div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0,1fr))", gap: 8 }}>
              {watch.map((p) => (
                <div key={`${p.symbol}-${p.ts}`} style={{ display: "flex", justifyContent: "space-between", background: "var(--bg-elevated,#1a2332)", border: "1px solid var(--border,#1e293b)", borderRadius: 8, padding: "8px 10px", fontFamily: "var(--font-mono, monospace)", fontSize: 12 }}>
                  <span>{p.symbol}</span>
                  <span>{typeof p.bid === "number" ? p.bid.toFixed(5) : "--"}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
