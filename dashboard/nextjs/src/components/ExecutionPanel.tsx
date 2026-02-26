'use client';

import { useExecution } from '@/lib/api';
import { formatTime } from '@/lib/timezone';

interface ExecutionPanelProps {
  pair: string;
}

export default function ExecutionPanel({ pair }: ExecutionPanelProps) {
  const { data: execution, isLoading, error: isError } = useExecution();

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
    execution.state === 'SIGNAL_READY' ? 'text-yellow-500' :
    execution.state === 'EXECUTING' ? 'text-wolf-green' :
    execution.state === 'COOLDOWN' ? 'text-wolf-red' :
    'text-wolf-gray-light';

  const stateIcon =
    execution.state === 'SIGNAL_READY' ? '⏳' :
    execution.state === 'EXECUTING' ? '✅' :
    execution.state === 'COOLDOWN' ? '❌' :
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
        {execution.cooldown_until && (
          <p className="text-sm text-wolf-gray-light mt-2">
            Cooldown until {formatTime(execution.cooldown_until)}
          </p>
        )}
      </div>

      {/* Order Details */}
      {execution.current_pair && (
        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-wolf-gray-light">Current Pair:</span>
            <span className="font-semibold">{execution.current_pair}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-wolf-gray-light">Signals:</span>
            <span className="font-semibold">{execution.signal_count}</span>
          </div>
        </div>
      )}

      {/* Timestamp */}
      {execution.last_execution && (
        <div className="mt-4 pt-4 border-t border-wolf-gray-light text-xs text-wolf-gray-light">
          <p>Last Update: {formatTime(execution.last_execution)}</p>
        </div>
      )}
    </div>
  );
}
