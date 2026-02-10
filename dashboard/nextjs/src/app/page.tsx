'use client';

import { useState } from 'react';
import PairSelector from '@/components/PairSelector';
import VerdictCard from '@/components/VerdictCard';
import GateStatus from '@/components/GateStatus';
import ExecutionPanel from '@/components/ExecutionPanel';
import TimezoneDisplay from '@/components/TimezoneDisplay';
import SystemHealth from '@/components/SystemHealth';

export default function Home() {
  const [selectedPair, setSelectedPair] = useState<string>('EURUSD');

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <header className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
          <div>
            <h1 className="text-3xl md:text-4xl font-bold text-wolf-gold mb-2">
              🐺 TUYUL FX WOLF
            </h1>
            <p className="text-wolf-gray-light text-sm">
              15-LAYER TRADING SYSTEM v7.4r∞
            </p>
          </div>
          <div className="flex flex-col items-start md:items-end gap-2">
            <TimezoneDisplay />
            <SystemHealth />
          </div>
        </header>

        {/* Pair Selector */}
        <PairSelector
          selectedPair={selectedPair}
          onSelectPair={setSelectedPair}
        />

        {/* Main Content Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* L12 Verdict */}
          <div className="lg:col-span-2">
            <VerdictCard pair={selectedPair} />
          </div>

          {/* Gate Status */}
          <div>
            <GateStatus pair={selectedPair} />
          </div>

          {/* Execution Panel */}
          <div>
            <ExecutionPanel pair={selectedPair} />
          </div>
        </div>

        {/* Footer */}
        <footer className="mt-8 pt-6 border-t border-wolf-gray text-center text-sm text-wolf-gray-light">
          <p>
            © 2026 TUYUL FX WOLF 15-LAYER SYSTEM | GMT+8 (Asia/Singapore)
          </p>
          <p className="mt-1 text-xs">
            Read-Only Dashboard | Constitutional Constraints Active
          </p>
        </footer>
      </div>
    </main>
  );
}
