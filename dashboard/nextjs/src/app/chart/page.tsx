'use client';

/**
 * Chart page — full-screen TradingView-style candlestick chart
 * with real-time candle updates via WebSocket.
 */

import CandleChart from '@/components/CandleChart';
import PriceTicker from '@/components/PriceTicker';

export default function ChartPage() {
  return (
    <div className="p-4 md:p-6">
      <div className="max-w-7xl mx-auto space-y-4">
        <header>
          <h1 className="text-2xl font-bold text-wolf-gold">Chart</h1>
          <p className="text-gray-500 text-xs">Real-time OHLC candlestick visualization</p>
        </header>

        {/* Price Ticker Strip */}
        <PriceTicker />

        {/* Main Chart */}
        <CandleChart
          symbol="EURUSD"
          symbols={['EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD', 'GBPJPY', 'AUDUSD']}
          height={600}
          initialTimeframe="M5"
        />
      </div>
    </div>
  );
}
