"use client";

import { useState } from "react";
import { TabPanel, Tabs, type TabItem } from "@/components/ui/Tabs";
import { NewsScreen } from "@/features/news/components/NewsScreen";
import { useLivePrices } from "@/lib/realtime/hooks/useLivePrices";

const TABS: TabItem[] = [
  { id: "chart", label: "CHART" },
  { id: "calendar", label: "CALENDAR" },
  { id: "news", label: "NEWS" },
  { id: "watchlist", label: "WATCHLIST" },
];

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

export default function MarketPage() {
  const [tab, setTab] = useState("chart");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold">Market</h1>
        <p className="font-mono text-xs text-[var(--text-muted)]">
          Chart, calendar, news, and watchlist in a single workspace.
        </p>
      </div>

      <Tabs tabs={TABS} activeTab={tab} onTabChange={setTab}>
        <TabPanel id="chart" activeTab={tab}>
          <TradingViewFrame
            title="TradingView Chart"
            src="https://s.tradingview.com/widgetembed/?symbol=OANDA:EURUSD&interval=60&theme=dark&style=1&timezone=Etc%2FUTC"
          />
        </TabPanel>
        <TabPanel id="calendar" activeTab={tab}>
          <TradingViewFrame
            title="Economic Calendar"
            src="https://s.tradingview.com/embed-widget/events/?locale=en&importance=0,1&colorTheme=dark&isTransparent=true"
          />
        </TabPanel>
        <TabPanel id="news" activeTab={tab}>
          <NewsScreen />
        </TabPanel>
        <TabPanel id="watchlist" activeTab={tab}>
          <WatchlistTab />
        </TabPanel>
      </Tabs>
    </div>
  );
}
