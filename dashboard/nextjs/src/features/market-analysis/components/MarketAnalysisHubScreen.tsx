"use client";

import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import PageComplianceBanner from "@/components/feedback/PageComplianceBanner";
import { DomainHeader } from "@/shared/ui/DomainHeader";
import { CandlestickChart } from "@/components/charts/CandlestickChart";
import { DataFreshnessBadge } from "@/components/realtime/DataFreshnessBadge";
import { useLiveCandles } from "@/lib/realtime/hooks/useLiveCandles";
import {
  usePricesREST,
  useProbabilityCalibration,
  useProbabilitySummary,
} from "@/shared/api/market.api";
import { useLivePrices } from "@/lib/realtime";
import { formatTime } from "@/lib/timezone";
import type { PriceData } from "@/types";

const SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "GBPJPY", "AUDUSD"];
const TIMEFRAMES = ["M1", "M5", "M15", "H1"] as const;

type TabKey = "charts" | "probability" | "prices";

export function MarketAnalysisHubScreen() {
  const params = useSearchParams();
  const initialTab = (params.get("tab") as TabKey) || "charts";
  const [tab, setTab] = useState<TabKey>(initialTab);

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <PageComplianceBanner page="analysis" />

      <DomainHeader
        domain="analysis"
        title="MARKET ANALYSIS"
        subtitle="Charts, probability health, and live prices in one utility domain"
      />

      <div style={{ display: "flex", gap: 8 }}>
        {(["charts", "probability", "prices"] as TabKey[]).map((item) => (
          <button
            key={item}
            onClick={() => setTab(item)}
            className="rounded-lg border px-3 py-2"
            style={{
              borderColor: tab === item ? "var(--accent, #00E5FF)" : "rgba(255,255,255,0.12)",
            }}
          >
            {item.toUpperCase()}
          </button>
        ))}
      </div>

      {tab === "charts" && <ChartsPanel />}
      {tab === "probability" && <ProbabilityPanel />}
      {tab === "prices" && <PricesPanel />}
    </div>
  );
}

function ChartsPanel() {
  const [selectedSymbol, setSelectedSymbol] = useState("EURUSD");
  const [selectedTimeframe, setSelectedTimeframe] = useState<(typeof TIMEFRAMES)[number]>("M1");

  const { candles, forming, status, isStale } = useLiveCandles(selectedSymbol);

  const lastUpdatedAt = useMemo(() => {
    if (forming?.timestamp) return forming.timestamp;
    if (candles.length > 0) return candles[candles.length - 1].timestamp;
    return null;
  }, [forming, candles]);

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div className="font-semibold">Realtime Charts</div>
        <DataFreshnessBadge
          lastUpdatedAt={lastUpdatedAt}
          connected={status === "LIVE"}
          staleThresholdSec={5}
        />
      </div>

      <div className="rounded-xl border p-3" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {SYMBOLS.map((sym) => (
          <button key={sym} onClick={() => setSelectedSymbol(sym)} className="rounded border px-3 py-2">
            {sym}
          </button>
        ))}
        {TIMEFRAMES.map((tf) => (
          <button key={tf} onClick={() => setSelectedTimeframe(tf)} className="rounded border px-3 py-2">
            {tf}
          </button>
        ))}
      </div>

      <CandlestickChart
        symbol={selectedSymbol}
        timeframe={selectedTimeframe}
        data={candles}
        forming={forming}
        height={480}
      />

      {isStale && (
        <div className="rounded-xl border p-3">Candle data may be stale. Waiting for backend updates...</div>
      )}
    </div>
  );
}

function ProbabilityPanel() {
  const { data: summary, isLoading } = useProbabilitySummary();
  const { data: calibration } = useProbabilityCalibration();

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
      <div className="rounded-xl border p-4">
        <div className="font-semibold">Probability Summary</div>
        {isLoading ? (
          <div style={{ marginTop: 8 }}>Loading...</div>
        ) : (
          <div style={{ marginTop: 8, display: "grid", gap: 6 }}>
            <div>Total Signals: {summary?.total_signals_today ?? 0}</div>
            <div>High Confidence: {summary?.high_confidence_signals ?? 0}</div>
            <div>Avg MC Win: {summary ? `${(summary.avg_mc_win_prob * 100).toFixed(1)}%` : "-"}</div>
            <div>
              Avg Bayesian: {summary ? `${(summary.avg_bayesian_confidence * 100).toFixed(1)}%` : "-"}
            </div>
          </div>
        )}
      </div>

      <div className="rounded-xl border p-4">
        <div className="font-semibold">Calibration</div>
        <div style={{ marginTop: 8, fontSize: 32, fontWeight: 800 }}>{calibration?.grade ?? "-"}</div>
        <div>Score: {calibration ? `${(calibration.score * 100).toFixed(1)}%` : "-"}</div>
      </div>
    </div>
  );
}

function PricesPanel() {
  const { data: restPrices, mutate } = usePricesREST();
  const { priceMap, status } = useLivePrices(true, false, () => mutate());

  const allPrices = useMemo((): PriceData[] => {
    const restMap: Record<string, PriceData> = {};
    for (const p of restPrices ?? []) restMap[p.symbol] = p;
    return Object.values({ ...restMap, ...priceMap }).sort((a, b) => a.symbol.localeCompare(b.symbol));
  }, [restPrices, priceMap]);

  return (
    <div className="rounded-xl border p-4">
      <div className="font-semibold">Live Prices</div>
      <div style={{ marginTop: 4, fontSize: 12, opacity: 0.8 }}>
        Source: {status === "LIVE" ? "WebSocket" : "REST"}
      </div>

      <div style={{ marginTop: 12, overflowX: "auto" }}>
        <table>
          <thead>
            <tr>
              <th>SYMBOL</th>
              <th>BID</th>
              <th>ASK</th>
              <th>SPREAD</th>
              <th>UPDATED</th>
            </tr>
          </thead>
          <tbody>
            {allPrices.map((p) => (
              <tr key={p.symbol}>
                <td>{p.symbol}</td>
                <td>{p.bid?.toFixed?.(5) ?? "-"}</td>
                <td>{p.ask?.toFixed?.(5) ?? "-"}</td>
                <td>{p.spread?.toFixed?.(1) ?? "-"}</td>
                <td>{p.timestamp ? formatTime(p.timestamp) : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
