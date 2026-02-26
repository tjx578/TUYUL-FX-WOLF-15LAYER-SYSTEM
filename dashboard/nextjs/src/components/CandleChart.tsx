'use client';

/**
 * TradingView Lightweight Charts integration for real-time candle visualization.
 *
 * Displays OHLC candlestick chart with live updating bars from the WebSocket
 * candle stream. Supports M1, M5, M15, H1 timeframes.
 */

import { useEffect, useRef, useState } from 'react';
import { useCandlesWS } from '@/lib/websocket';
import type { CandleData } from '@/types';
import clsx from 'clsx';

// Dynamically import lightweight-charts (browser only)
let createChart: any = null;

const TIMEFRAMES = ['M1', 'M5', 'M15', 'H1'] as const;
type Timeframe = (typeof TIMEFRAMES)[number];

interface CandleChartProps {
  /** Default symbol to display */
  symbol?: string;
  /** Available symbols */
  symbols?: string[];
  /** Initial timeframe */
  initialTimeframe?: Timeframe;
  /** Chart height in pixels */
  height?: number;
}

export default function CandleChart({
  symbol: initialSymbol = 'EURUSD',
  symbols = ['EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD', 'GBPJPY'],
  initialTimeframe = 'M5',
  height = 500,
}: CandleChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const seriesRef = useRef<any>(null);

  const [symbol, setSymbol] = useState(initialSymbol);
  const [timeframe, setTimeframe] = useState<Timeframe>(initialTimeframe);
  const [chartReady, setChartReady] = useState(false);

  const { data: candleData } = useCandlesWS(symbol, timeframe);

  // Initialize chart
  useEffect(() => {
    let mounted = true;

    const initChart = async () => {
      if (!chartContainerRef.current) return;

      try {
        // Dynamic import for browser-only module
        const lwc = await import('lightweight-charts');
        createChart = lwc.createChart;

        if (!mounted || !chartContainerRef.current) return;

        // Remove old chart
        if (chartRef.current) {
          chartRef.current.remove();
        }

        const chart = createChart(chartContainerRef.current, {
          width: chartContainerRef.current.clientWidth,
          height,
          layout: {
            background: { color: '#0a0a0a' },
            textColor: '#9ca3af',
            fontSize: 12,
            fontFamily: "'JetBrains Mono', monospace",
          },
          grid: {
            vertLines: { color: '#1a1a1a' },
            horzLines: { color: '#1a1a1a' },
          },
          crosshair: {
            mode: 0,
            vertLine: { color: '#d4af3780', width: 1, style: 2 },
            horzLine: { color: '#d4af3780', width: 1, style: 2 },
          },
          timeScale: {
            timeVisible: true,
            secondsVisible: false,
            borderColor: '#1a1a1a',
          },
          rightPriceScale: {
            borderColor: '#1a1a1a',
          },
        });

        const series = chart.addCandlestickSeries({
          upColor: '#10b981',
          downColor: '#ef4444',
          borderUpColor: '#10b981',
          borderDownColor: '#ef4444',
          wickUpColor: '#10b981',
          wickDownColor: '#ef4444',
        });

        chartRef.current = chart;
        seriesRef.current = series;
        setChartReady(true);

        // Resize handler
        const resizeObserver = new ResizeObserver((entries) => {
          if (entries[0] && chartRef.current) {
            const { width } = entries[0].contentRect;
            chartRef.current.applyOptions({ width });
          }
        });
        resizeObserver.observe(chartContainerRef.current);

        return () => {
          resizeObserver.disconnect();
          chart.remove();
        };
      } catch (err) {
        console.error('Failed to load chart library:', err);
      }
    };

    initChart();

    return () => {
      mounted = false;
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
        seriesRef.current = null;
        setChartReady(false);
      }
    };
  }, [height]);

  // Update chart data when candle data changes
  useEffect(() => {
    if (!chartReady || !seriesRef.current || !candleData) return;

    // Convert CandleData to lightweight-charts format
    const lwcBar = {
      time: candleData.timestamp as any, // Unix timestamp
      open: candleData.open,
      high: candleData.high,
      low: candleData.low,
      close: candleData.close,
    };

    try {
      seriesRef.current.update(lwcBar);
    } catch {
      // If update fails, try setting data array
      seriesRef.current.setData([lwcBar]);
    }
  }, [candleData, symbol, timeframe, chartReady]);

  // Current candle info
  const currentBar = candleData;

  return (
    <div className="rounded-lg border border-wolf-gray bg-wolf-dark/50 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-wolf-gray">
        {/* Symbol selector */}
        <div className="flex items-center gap-2">
          {symbols.map((s) => (
            <button
              key={s}
              onClick={() => setSymbol(s)}
              className={clsx(
                'px-2 py-0.5 rounded text-xs font-bold transition-colors',
                s === symbol
                  ? 'bg-wolf-gold/20 text-wolf-gold'
                  : 'text-gray-500 hover:text-gray-300'
              )}
            >
              {s}
            </button>
          ))}
        </div>

        {/* Timeframe selector */}
        <div className="flex items-center gap-1">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              onClick={() => setTimeframe(tf)}
              className={clsx(
                'px-2 py-0.5 rounded text-xs font-mono transition-colors',
                tf === timeframe
                  ? 'bg-wolf-blue/20 text-wolf-blue'
                  : 'text-gray-500 hover:text-gray-300'
              )}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      {/* Current bar info */}
      {currentBar && (
        <div className="flex items-center gap-4 px-4 py-1 border-b border-wolf-gray/50 text-xs font-mono">
          <span className="text-gray-400">O: <span className="text-gray-200">{currentBar.open.toFixed(5)}</span></span>
          <span className="text-gray-400">H: <span className="text-emerald-400">{currentBar.high.toFixed(5)}</span></span>
          <span className="text-gray-400">L: <span className="text-red-400">{currentBar.low.toFixed(5)}</span></span>
          <span className={clsx('text-gray-400', currentBar.close >= currentBar.open ? 'text-emerald-400' : 'text-red-400')}>
            C: <span>{currentBar.close.toFixed(5)}</span>
          </span>
          <span className="text-gray-400">Vol: <span className="text-gray-200">{currentBar.volume}</span></span>
        </div>
      )}

      {/* Chart canvas */}
      <div ref={chartContainerRef} style={{ height }} className="w-full" />
    </div>
  );
}
