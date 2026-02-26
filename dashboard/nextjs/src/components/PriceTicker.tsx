'use client';

import { usePriceMap } from '@/lib/websocket';
import type { PriceData } from '@/types';
import clsx from 'clsx';
import { useEffect, useRef, useState } from 'react';

interface PriceTickerProps {
  /** Symbols to display (if empty, shows all) */
  symbols?: string[];
  /** Compact mode for sidebar use */
  compact?: boolean;
}

/**
 * Real-time price ticker powered by WebSocket tick-by-tick stream.
 */
export default function PriceTicker({ symbols, compact = false }: PriceTickerProps) {
  const { priceMap: prices, connected } = usePriceMap();
  const [flashes, setFlashes] = useState<Record<string, 'up' | 'down' | null>>({});
  const prevPrices = useRef<Record<string, number>>({});

  // Flash effect on price change
  useEffect(() => {
    const newFlashes: Record<string, 'up' | 'down' | null> = {};
    let hasChange = false;

    for (const [symbol, tick] of Object.entries(prices)) {
      const mid = (tick.bid + tick.ask) / 2;
      const prev = prevPrices.current[symbol];
      if (prev !== undefined && mid !== prev) {
        newFlashes[symbol] = mid > prev ? 'up' : 'down';
        hasChange = true;
      }
      prevPrices.current[symbol] = mid;
    }

    if (hasChange) {
      setFlashes((prev) => ({ ...prev, ...newFlashes }));
      // Clear flashes after 300ms
      const timer = setTimeout(() => setFlashes({}), 300);
      return () => clearTimeout(timer);
    }
  }, [prices]);

  const filteredSymbols = symbols
    ? symbols.filter((s) => s in prices)
    : Object.keys(prices).sort();

  if (filteredSymbols.length === 0) {
    return (
      <div className="text-gray-500 text-xs p-2">
        {connected ? 'Connecting...' : 'No price data'}
      </div>
    );
  }

  return (
    <div className={clsx('grid gap-1', compact ? 'grid-cols-1' : 'grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6')}>
      {filteredSymbols.map((symbol) => {
        const tick = prices[symbol];
        const spread = tick ? ((tick.ask - tick.bid) * (symbol.includes('JPY') ? 100 : 10000)).toFixed(1) : '—';
        const flash = flashes[symbol];

        return (
          <div
            key={symbol}
            className={clsx(
              'rounded-md border px-2 py-1.5 transition-colors duration-150',
              'border-wolf-gray bg-wolf-dark/50',
              flash === 'up' && 'bg-emerald-900/30 border-emerald-700/50',
              flash === 'down' && 'bg-red-900/30 border-red-700/50'
            )}
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-gray-300">{symbol}</span>
              <span className="text-[10px] text-gray-500">{spread}p</span>
            </div>
            <div className="flex items-center justify-between mt-0.5">
              <span className={clsx('text-xs font-mono', flash === 'up' ? 'text-emerald-400' : flash === 'down' ? 'text-red-400' : 'text-gray-200')}>
                {tick?.bid?.toFixed(symbol.includes('JPY') ? 3 : 5) ?? '—'}
              </span>
              <span className={clsx('text-xs font-mono', flash === 'up' ? 'text-emerald-400' : flash === 'down' ? 'text-red-400' : 'text-gray-200')}>
                {tick?.ask?.toFixed(symbol.includes('JPY') ? 3 : 5) ?? '—'}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
