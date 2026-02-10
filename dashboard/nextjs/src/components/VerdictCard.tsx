'use client';

import { useVerdict } from '@/lib/api';
import { formatLocalTime, formatUTCTime } from '@/lib/timezone';
import { Activity } from 'lucide-react';

interface VerdictCardProps {
  pair: string;
}

export default function VerdictCard({ pair }: VerdictCardProps) {
  const { verdict, isLoading, isError } = useVerdict(pair);

  if (isLoading) {
    return (
      <div className="bg-wolf-gray rounded-lg p-6 border border-wolf-gray-light">
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-wolf-gray-light rounded w-1/3"></div>
          <div className="h-6 bg-wolf-gray-light rounded w-1/2"></div>
          <div className="h-4 bg-wolf-gray-light rounded w-2/3"></div>
        </div>
      </div>
    );
  }

  if (isError || !verdict) {
    return (
      <div className="bg-wolf-gray rounded-lg p-6 border border-red-500/20">
        <p className="text-red-500">⚠️ Failed to load verdict for {pair}</p>
      </div>
    );
  }

  const verdictColor =
    verdict.verdict.startsWith('EXECUTE') ? 'text-wolf-green' :
    verdict.verdict === 'HOLD' ? 'text-yellow-500' :
    'text-wolf-red';

  const wolfStatusIcon =
    verdict.wolf_status === 'ALPHA' ? '👑' :
    verdict.wolf_status === 'PACK' ? '🐺' :
    verdict.wolf_status === 'SCOUT' ? '👁️' :
    '🚫';

  return (
    <div className="bg-wolf-gray rounded-lg p-6 border border-wolf-gray-light">
      {/* Header */}
      <div className="flex justify-between items-start mb-6">
        <div>
          <h2 className="text-2xl font-bold text-wolf-gold mb-1">
            🐺 L12 VERDICT
          </h2>
          <p className="text-sm text-wolf-gray-light">
            {pair} • {verdict.schema}
          </p>
        </div>
        <div className="text-right">
          <div className="text-3xl mb-1">{wolfStatusIcon}</div>
          <p className="text-xs text-wolf-gray-light">{verdict.wolf_status}</p>
        </div>
      </div>

      {/* Verdict Status */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-wolf-darker p-4 rounded-lg">
          <p className="text-xs text-wolf-gray-light mb-1">Verdict</p>
          <p className={`text-lg font-bold ${verdictColor}`}>
            {verdict.verdict}
          </p>
        </div>
        <div className="bg-wolf-darker p-4 rounded-lg">
          <p className="text-xs text-wolf-gray-light mb-1">Confidence</p>
          <p className="text-lg font-bold text-wolf-gold">
            {verdict.confidence}
          </p>
        </div>
        <div className="bg-wolf-darker p-4 rounded-lg">
          <p className="text-xs text-wolf-gray-light mb-1">Wolf Score</p>
          <p className="text-lg font-bold text-white">
            {verdict.scores.wolf_30_point}/30
          </p>
        </div>
        <div className="bg-wolf-darker p-4 rounded-lg">
          <p className="text-xs text-wolf-gray-light mb-1">Gates Passed</p>
          <p className="text-lg font-bold text-white">
            {verdict.gates.passed}/{verdict.gates.total}
          </p>
        </div>
      </div>

      {/* Execution Details */}
      {verdict.execution.direction && (
        <div className="bg-wolf-darker p-4 rounded-lg mb-6">
          <h3 className="text-sm font-semibold text-wolf-gold mb-3">
            EXECUTION DETAILS
          </h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <div>
              <p className="text-wolf-gray-light text-xs">Direction</p>
              <p className="font-mono-numbers font-semibold">
                {verdict.execution.direction}
              </p>
            </div>
            <div>
              <p className="text-wolf-gray-light text-xs">Entry</p>
              <p className="font-mono-numbers">
                {verdict.execution.entry_price?.toFixed(5) || 'N/A'}
              </p>
            </div>
            <div>
              <p className="text-wolf-gray-light text-xs">Stop Loss</p>
              <p className="font-mono-numbers">
                {verdict.execution.stop_loss?.toFixed(5) || 'N/A'}
              </p>
            </div>
            <div>
              <p className="text-wolf-gray-light text-xs">Take Profit</p>
              <p className="font-mono-numbers">
                {verdict.execution.take_profit_1?.toFixed(5) || 'N/A'}
              </p>
            </div>
            <div>
              <p className="text-wolf-gray-light text-xs">R:R Ratio</p>
              <p className="font-mono-numbers">
                {verdict.execution.rr_ratio?.toFixed(2) || 'N/A'}
              </p>
            </div>
            <div>
              <p className="text-wolf-gray-light text-xs">Risk %</p>
              <p className="font-mono-numbers">
                {verdict.execution.risk_percent?.toFixed(2) || 'N/A'}%
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Timestamps */}
      <div className="text-xs text-wolf-gray-light space-y-1">
        <p>
          <span className="text-wolf-gold">UTC:</span> {formatUTCTime(verdict.timestamp)}
        </p>
        <p>
          <span className="text-wolf-gold">Local (GMT+8):</span> {formatLocalTime(verdict.timestamp)}
        </p>
      </div>
    </div>
  );
}
