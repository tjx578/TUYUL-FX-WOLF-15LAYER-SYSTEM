'use client';

/**
 * Equity Curve & P&L Distribution charts using Recharts.
 *
 * Provides visual analytics for the risk dashboard:
 * - Equity curve over time
 * - P&L distribution histogram
 * - Drawdown visualization
 */

import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  BarChart,
  Bar,
  Cell,
  ReferenceLine,
} from 'recharts';

// ---------------------------------------------------------------------------
// Equity Curve
// ---------------------------------------------------------------------------

interface EquityPoint {
  date: string;
  equity: number;
  balance: number;
  drawdown?: number;
}

interface EquityCurveProps {
  data: EquityPoint[];
  height?: number;
}

export function EquityCurve({ data, height = 280 }: EquityCurveProps) {
  if (!data.length) {
    return (
      <div className="rounded-lg border border-wolf-gray bg-wolf-dark/50 p-4">
        <h3 className="text-sm font-bold text-gray-200 mb-2">Equity Curve</h3>
        <div className="flex items-center justify-center h-40 text-gray-500 text-xs">
          No equity data available
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-wolf-gray bg-wolf-dark/50 p-4">
      <h3 className="text-sm font-bold text-gray-200 mb-3">Equity Curve</h3>
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data} margin={{ top: 5, right: 5, left: 5, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" />
          <XAxis
            dataKey="date"
            tick={{ fill: '#6b7280', fontSize: 10 }}
            stroke="#1a1a1a"
          />
          <YAxis
            tick={{ fill: '#6b7280', fontSize: 10 }}
            stroke="#1a1a1a"
            tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: '#0a0a0a',
              border: '1px solid #2a2a2a',
              borderRadius: '8px',
              fontSize: 11,
            }}
            labelStyle={{ color: '#9ca3af' }}
            formatter={(value: number, name: string) => [
              `$${value.toLocaleString('en-US', { minimumFractionDigits: 2 })}`,
              name === 'equity' ? 'Equity' : 'Balance',
            ]}
          />
          <Area
            type="monotone"
            dataKey="balance"
            stroke="#3b82f6"
            fill="#3b82f620"
            strokeWidth={1}
          />
          <Area
            type="monotone"
            dataKey="equity"
            stroke="#d4af37"
            fill="#d4af3720"
            strokeWidth={2}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}


// ---------------------------------------------------------------------------
// P&L Distribution
// ---------------------------------------------------------------------------

interface PnLBar {
  range: string;
  count: number;
  isPositive: boolean;
}

interface PnLDistributionProps {
  data: PnLBar[];
  height?: number;
}

export function PnLDistribution({ data, height = 200 }: PnLDistributionProps) {
  if (!data.length) {
    return (
      <div className="rounded-lg border border-wolf-gray bg-wolf-dark/50 p-4">
        <h3 className="text-sm font-bold text-gray-200 mb-2">P&L Distribution</h3>
        <div className="flex items-center justify-center h-32 text-gray-500 text-xs">
          No trade data for distribution
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-wolf-gray bg-wolf-dark/50 p-4">
      <h3 className="text-sm font-bold text-gray-200 mb-3">P&L Distribution</h3>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 5, right: 5, left: 5, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" />
          <XAxis
            dataKey="range"
            tick={{ fill: '#6b7280', fontSize: 9 }}
            stroke="#1a1a1a"
          />
          <YAxis
            tick={{ fill: '#6b7280', fontSize: 10 }}
            stroke="#1a1a1a"
          />
          <Tooltip
            contentStyle={{
              backgroundColor: '#0a0a0a',
              border: '1px solid #2a2a2a',
              borderRadius: '8px',
              fontSize: 11,
            }}
          />
          <ReferenceLine y={0} stroke="#2a2a2a" />
          <Bar dataKey="count" radius={[3, 3, 0, 0]}>
            {data.map((entry, idx) => (
              <Cell
                key={idx}
                fill={entry.isPositive ? '#10b981' : '#ef4444'}
                fillOpacity={0.7}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Drawdown Chart
// ---------------------------------------------------------------------------

interface DrawdownPoint {
  date: string;
  drawdown: number;
}

interface DrawdownChartProps {
  data: DrawdownPoint[];
  maxDD?: number;
  height?: number;
}

export function DrawdownChart({ data, maxDD = 10, height = 180 }: DrawdownChartProps) {
  if (!data.length) {
    return (
      <div className="rounded-lg border border-wolf-gray bg-wolf-dark/50 p-4">
        <h3 className="text-sm font-bold text-gray-200 mb-2">Drawdown History</h3>
        <div className="flex items-center justify-center h-28 text-gray-500 text-xs">
          No drawdown data
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-wolf-gray bg-wolf-dark/50 p-4">
      <h3 className="text-sm font-bold text-gray-200 mb-3">Drawdown History</h3>
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data} margin={{ top: 5, right: 5, left: 5, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" />
          <XAxis
            dataKey="date"
            tick={{ fill: '#6b7280', fontSize: 10 }}
            stroke="#1a1a1a"
          />
          <YAxis
            tick={{ fill: '#6b7280', fontSize: 10 }}
            stroke="#1a1a1a"
            domain={[0, maxDD]}
            tickFormatter={(v) => `${v}%`}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: '#0a0a0a',
              border: '1px solid #2a2a2a',
              borderRadius: '8px',
              fontSize: 11,
            }}
            formatter={(value: number) => [`${value.toFixed(2)}%`, 'Drawdown']}
          />
          <ReferenceLine
            y={maxDD * 0.8}
            stroke="#ef4444"
            strokeDasharray="5 5"
            label={{ value: 'Critical', fill: '#ef4444', fontSize: 10 }}
          />
          <Area
            type="monotone"
            dataKey="drawdown"
            stroke="#ef4444"
            fill="#ef444420"
            strokeWidth={2}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
