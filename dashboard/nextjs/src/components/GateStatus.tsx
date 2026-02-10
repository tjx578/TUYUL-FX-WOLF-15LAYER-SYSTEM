'use client';

import { useVerdict } from '@/lib/api';
import { CheckCircle2, XCircle } from 'lucide-react';

interface GateStatusProps {
  pair: string;
}

export default function GateStatus({ pair }: GateStatusProps) {
  const { verdict, isLoading, isError } = useVerdict(pair);

  if (isLoading) {
    return (
      <div className="bg-wolf-gray rounded-lg p-6 border border-wolf-gray-light">
        <div className="animate-pulse space-y-3">
          <div className="h-6 bg-wolf-gray-light rounded w-1/2"></div>
          {[...Array(9)].map((_, i) => (
            <div key={i} className="h-8 bg-wolf-gray-light rounded"></div>
          ))}
        </div>
      </div>
    );
  }

  if (isError || !verdict) {
    return (
      <div className="bg-wolf-gray rounded-lg p-6 border border-red-500/20">
        <p className="text-red-500">⚠️ Failed to load gates</p>
      </div>
    );
  }

  const gates = [
    { key: 'gate_1_tii', label: 'TII Symmetry' },
    { key: 'gate_2_integrity', label: 'Integrity Index' },
    { key: 'gate_3_rr', label: 'Risk:Reward Ratio' },
    { key: 'gate_4_fta', label: 'FTA Score' },
    { key: 'gate_5_montecarlo', label: 'Monte Carlo Win' },
    { key: 'gate_6_propfirm', label: 'Prop Firm Compliance' },
    { key: 'gate_7_drawdown', label: 'Drawdown Check' },
    { key: 'gate_8_latency', label: 'System Latency' },
    { key: 'gate_9_conf12', label: 'L12 Confidence' },
  ];

  return (
    <div className="bg-wolf-gray rounded-lg p-6 border border-wolf-gray-light">
      {/* Header */}
      <div className="mb-6">
        <h2 className="text-xl font-bold text-wolf-gold mb-2">
          🚪 9-GATE STATUS
        </h2>
        <p className="text-sm text-wolf-gray-light">
          Constitutional validation checkpoints
        </p>
      </div>

      {/* Gates Grid */}
      <div className="space-y-2">
        {gates.map(({ key, label }) => {
          const status = verdict.gates[key as keyof typeof verdict.gates];
          const isPassed = status === 'PASS';

          return (
            <div
              key={key}
              className={`flex items-center justify-between p-3 rounded-lg ${
                isPassed
                  ? 'bg-wolf-green/10 border border-wolf-green/20'
                  : 'bg-wolf-red/10 border border-wolf-red/20'
              }`}
            >
              <div className="flex items-center gap-3">
                {isPassed ? (
                  <CheckCircle2 className="w-5 h-5 text-wolf-green" />
                ) : (
                  <XCircle className="w-5 h-5 text-wolf-red" />
                )}
                <span className="text-sm font-medium">{label}</span>
              </div>
              <span
                className={`text-xs font-bold ${
                  isPassed ? 'text-wolf-green' : 'text-wolf-red'
                }`}
              >
                {String(status)}
              </span>
            </div>
          );
        })}
      </div>

      {/* Summary */}
      <div className="mt-6 pt-6 border-t border-wolf-gray-light">
        <div className="flex justify-between items-center">
          <span className="text-sm text-wolf-gray-light">Total Status</span>
          <span className="text-lg font-bold">
            <span className="text-wolf-green">{verdict.gates.passed}</span>
            <span className="text-wolf-gray-light"> / </span>
            <span className="text-white">{verdict.gates.total}</span>
          </span>
        </div>
      </div>
    </div>
  );
}
