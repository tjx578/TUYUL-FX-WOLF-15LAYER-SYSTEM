'use client';

/**
 * Trades page — full trade ledger with history and management.
 */

import TradeHistory from '@/components/TradeHistory';
import PriceTicker from '@/components/PriceTicker';

export default function TradesPage() {
  return (
    <div className="p-4 md:p-6">
      <div className="max-w-7xl mx-auto space-y-4">
        <header>
          <h1 className="text-2xl font-bold text-wolf-gold">Trades</h1>
          <p className="text-gray-500 text-xs">Trade ledger — active, pending, and closed positions</p>
        </header>

        {/* Live Prices */}
        <PriceTicker />

        {/* Trade Table */}
        <TradeHistory />
      </div>
    </div>
  );
}
