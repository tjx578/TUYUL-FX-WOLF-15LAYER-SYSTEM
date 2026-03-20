"use client";

/**
 * TUYUL FX Wolf-15 — Candlestick Chart
 *
 * High-impact visual component for traders. Features:
 *   - Render candle snapshot
 *   - Update forming candle in realtime
 *   - Append closed candles
 *   - Auto-resize
 *   - Dark theme matching dashboard aesthetic
 *   - Ready for signal/verdict overlay (future)
 */

import { useEffect, useMemo, useRef } from "react";
import { createChart, ColorType, type IChartApi, type ISeriesApi, type CandlestickData, type Time } from "lightweight-charts";
import type { CandleData } from "@/types";

interface CandlestickChartProps {
  /** Trading pair symbol (e.g. "EURUSD") */
  symbol: string;
  /** Timeframe label for display */
  timeframe: string;
  /** Historical candle data */
  data: CandleData[];
  /** Currently forming (partial) candle */
  forming?: CandleData | null;
  /** Chart height in pixels */
  height?: number;
}

function toChartData(c: CandleData): CandlestickData<Time> {
  return {
    time: Math.floor(c.timestamp / 1000) as Time,
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
  };
}

export function CandlestickChart({
  symbol,
  timeframe,
  data,
  forming,
  height = 360,
}: CandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  // Merge history + forming candle
  const merged = useMemo(() => {
    const chartData = data.map(toChartData);
    if (!forming) return chartData;

    const formingData = toChartData(forming);
    if (chartData.length === 0) return [formingData];

    const last = chartData[chartData.length - 1];
    if (last.time === formingData.time) {
      return [...chartData.slice(0, -1), formingData];
    }
    return [...chartData, formingData];
  }, [data, forming]);

  // Initialize chart once
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: "#0A0C10" },
        textColor: "#9A9DA6",
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.04)" },
        horzLines: { color: "rgba(255,255,255,0.04)" },
      },
      rightPriceScale: {
        borderColor: "rgba(255,255,255,0.08)",
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        borderColor: "rgba(255,255,255,0.08)",
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: {
        vertLine: { color: "rgba(0,229,255,0.4)", width: 1, style: 2 },
        horzLine: { color: "rgba(0,229,255,0.4)", width: 1, style: 2 },
      },
    });

    const series = chart.addCandlestickSeries({
      upColor: "#00F5A0",
      downColor: "#FF4757",
      borderUpColor: "#00F5A0",
      borderDownColor: "#FF4757",
      wickUpColor: "#00F5A0",
      wickDownColor: "#FF4757",
    });

    series.setData(merged);
    chart.timeScale().fitContent();

    chartRef.current = chart;
    seriesRef.current = series;

    // Handle resize
    const handleResize = () => {
      if (!containerRef.current || !chartRef.current) return;
      chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
    };

    handleResize();
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height]);

  // Update data when merged changes
  useEffect(() => {
    if (!seriesRef.current) return;
    seriesRef.current.setData(merged);
  }, [merged]);

  const latestPrice = merged.length > 0 ? merged[merged.length - 1].close : null;
  const priceChange = merged.length >= 2
    ? merged[merged.length - 1].close - merged[merged.length - 2].close
    : 0;
  const isPositive = priceChange >= 0;

  return (
    <div
      style={{
        borderRadius: 16,
        border: "1px solid rgba(255,255,255,0.08)",
        background: "#0A0C10",
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "14px 18px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          borderBottom: "1px solid rgba(255,255,255,0.06)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span
            style={{
              fontSize: 14,
              fontWeight: 700,
              letterSpacing: "0.04em",
              color: "var(--text-primary)",
            }}
          >
            {symbol}
          </span>
          <span
            style={{
              fontSize: 10,
              fontFamily: "var(--font-mono)",
              letterSpacing: "0.08em",
              color: "var(--text-muted)",
              padding: "4px 8px",
              background: "rgba(255,255,255,0.04)",
              borderRadius: 6,
            }}
          >
            {timeframe}
          </span>
        </div>

        {latestPrice !== null && (
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span
              style={{
                fontSize: 14,
                fontWeight: 600,
                fontFamily: "var(--font-mono)",
                color: "var(--text-primary)",
              }}
            >
              {latestPrice.toFixed(5)}
            </span>
            <span
              style={{
                fontSize: 11,
                fontFamily: "var(--font-mono)",
                color: isPositive ? "var(--green)" : "var(--red)",
              }}
            >
              {isPositive ? "+" : ""}
              {priceChange.toFixed(5)}
            </span>
          </div>
        )}
      </div>

      {/* Chart container */}
      <div ref={containerRef} style={{ width: "100%" }} />
    </div>
  );
}

export default CandlestickChart;
