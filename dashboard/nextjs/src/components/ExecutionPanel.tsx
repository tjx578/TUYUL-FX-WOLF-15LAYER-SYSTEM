'use client';

import { useExecution } from '@/lib/api';
import { formatLocalTime } from '@/lib/timezone';
import { Activity } from 'lucide-react';

interface ExecutionPanelProps {
  pair: string;
}

export default function ExecutionPanel({ pair }: ExecutionPanelProps) {
  const { execution, isLoading, isError } = useExecution();

  if (isLoading) {
    return (
      <div className="bg-wolf-gray rounded-lg p-6 border border-wolf-gray-light">
        <div className="animate-pulse space-y-3">
          <div className="h-6 bg-wolf-gray-light rounded w-1/2"></div>
          <div className="h-20 bg-wolf-gray-light rounded"></div>
        </div>
      </div>
    );
  }

  if (isError || !execution) {
    return (
      <div className="bg-wolf-gray rounded-lg p-6 border border-red-500/20">
        <p className="text-red-500">⚠️ Failed to load execution state</p>
      </div>
    );
  }

  const stateColor =
    execution.state === 'PENDING_ACTIVE' ? 'text-yellow-500' :
    execution.state === 'FILLED' ? 'text-wolf-green' :
    execution.state === 'CANCELLED' ? 'text-wolf-red' :
    'text-wolf-gray-light';

  const stateIcon =
    execution.state === 'PENDING_ACTIVE' ? '⏳' :
    execution.state === 'FILLED' ? '✅' :
    execution.state === 'CANCELLED' ? '❌' :
    '💤';

  return (
    <div className="bg-wolf-gray rounded-lg p-6 border border-wolf-gray-light">
      {/* Header */}
      <div className="mb-6">
        <h2 className="text-xl font-bold text-wolf-gold mb-2">
          ⚡ EXECUTION STATE
        </h2>
        <p className="text-sm text-wolf-gray-light">
          Current order status
        </p>
      </div>

      {/* State Display */}
      <div className="bg-wolf-darker p-6 rounded-lg text-center mb-4">
        <div className="text-5xl mb-2">{stateIcon}</div>
        <p className={`text-2xl font-bold ${stateColor}`}>
          {execution.state}
        </p>
        {execution.reason && (
          <p className="text-sm text-wolf-gray-light mt-2">
            {execution.reason}
          </p>
        )}
      </div>

      {/* Order Details */}
      {execution.order && (
        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-wolf-gray-light">Symbol:</span>
            <span className="font-semibold">{execution.order.symbol || 'N/A'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-wolf-gray-light">Direction:</span>
            <span className="font-semibold">{execution.order.direction || 'N/A'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-wolf-gray-light">Entry:</span>
            <span className="font-mono-numbers">
              {execution.order.entry || 'N/A'}
            </span>
          </div>
        </div>
      )}

      {/* Timestamp */}
      {execution.timestamp && (
        <div className="mt-4 pt-4 border-t border-wolf-gray-light text-xs text-wolf-gray-light">
          <p>Last Update: {formatLocalTime(execution.timestamp)}</p>
        </div>
      )}
    </div>
  );
}
