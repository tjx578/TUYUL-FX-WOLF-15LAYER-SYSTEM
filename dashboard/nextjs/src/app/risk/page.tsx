'use client';

/**
 * Risk page — drawdown, circuit breaker, prop firm compliance dashboard.
 */

import RiskDashboard from '@/components/RiskDashboard';
import { EquityCurve, DrawdownChart, PnLDistribution } from '@/components/RiskCharts';

// Demo data — in production these would come from journal/ledger API endpoints
const DEMO_EQUITY: { date: string; equity: number; balance: number }[] = [];
const DEMO_DRAWDOWN: { date: string; drawdown: number }[] = [];
const DEMO_PNL: { range: string; count: number; isPositive: boolean }[] = [];

export default function RiskPage() {
  return (
    <div className="p-4 md:p-6">
      <div className="max-w-7xl mx-auto space-y-4">
        <header>
          <h1 className="text-2xl font-bold text-wolf-gold">Risk Management</h1>
          <p className="text-gray-500 text-xs">
            Real-time risk monitoring — drawdown, circuit breaker, prop firm guard, position sizing
          </p>
        </header>

        {/* Live Risk Indicators */}
        <RiskDashboard />

        {/* Charts Section */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <EquityCurve data={DEMO_EQUITY} />
          <DrawdownChart data={DEMO_DRAWDOWN} />
        </div>

        <PnLDistribution data={DEMO_PNL} />
      </div>
    </div>
  );
}
