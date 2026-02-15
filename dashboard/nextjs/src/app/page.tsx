'use client';

import { useState } from 'react';
import PairSelector from '@/components/PairSelector';
import VerdictCard from '@/components/VerdictCard';
import GateStatus from '@/components/GateStatus';
import ExecutionPanel from '@/components/ExecutionPanel';
import TimezoneDisplay from '@/components/TimezoneDisplay';
import SystemHealth from '@/components/SystemHealth';
import PriceTicker from '@/components/PriceTicker';
import TradeHistory from '@/components/TradeHistory';

export default function Home() {
  const [selectedPair, setSelectedPair] = useState<string>('EURUSD');

  return (
    <div className="p-4 md:p-6">
      <div className="max-w-7xl mx-auto space-y-4">
        {/* Header */}
        <header className="flex flex-col md:flex-row justify-between items-start md:items-center gap-3">
          <div>
            <h1 className="text-2xl md:text-3xl font-bold text-wolf-gold">
              Dashboard
            </h1>
            <p className="text-gray-500 text-xs">
              Real-time overview | Constitutional Constraints Active
            </p>
          </div>
          <div className="flex flex-col items-start md:items-end gap-2">
            <TimezoneDisplay />
            <SystemHealth />
          </div>
        </header>

        {/* Live Price Ticker */}
        <section>
          <h2 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">Live Prices</h2>
          <PriceTicker />
        </section>

        {/* Pair Selector */}
        <PairSelector
          selectedPair={selectedPair}
          onSelectPair={setSelectedPair}
        />

        {/* Main Content Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* L12 Verdict */}
          <div className="lg:col-span-2">
            <VerdictCard pair={selectedPair} />
          </div>

          {/* Gate Status */}
          <GateStatus pair={selectedPair} />

          {/* Execution Panel */}
          <ExecutionPanel pair={selectedPair} />
        </div>

        {/* Active Trades */}
        <section>
          <h2 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">Active Trades</h2>
          <TradeHistory />
        </section>

        {/* Footer */}
        <footer className="mt-6 pt-4 border-t border-wolf-gray text-center text-xs text-gray-600">
          <p>© 2026 TUYUL FX WOLF 15-LAYER SYSTEM | GMT+8 (Asia/Singapore)</p>
        </footer>
      </div>
    </div>
  );
}
