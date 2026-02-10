'use client';

import { useHealth } from '@/lib/api';
import { Activity, Wifi, WifiOff } from 'lucide-react';

export default function SystemHealth() {
  const { health, isLoading, isError } = useHealth();

  const isHealthy = health?.status === 'healthy';

  return (
    <div className={`bg-wolf-gray rounded-lg p-3 border ${
      isHealthy ? 'border-wolf-green/20' : 'border-wolf-red/20'
    }`}>
      <div className="flex items-center gap-2 mb-2">
        {isHealthy ? (
          <Wifi className="w-4 h-4 text-wolf-green" />
        ) : (
          <WifiOff className="w-4 h-4 text-wolf-red" />
        )}
        <span className="text-xs font-semibold text-wolf-gold">SYSTEM</span>
      </div>
      <div className="space-y-1 text-xs">
        <div className="flex justify-between">
          <span className="text-wolf-gray-light">Status:</span>
          <span className={isHealthy ? 'text-wolf-green' : 'text-wolf-red'}>
            {isLoading ? 'Checking...' : isError ? 'Offline' : health?.status || 'Unknown'}
          </span>
        </div>
        {health?.latency_ms !== undefined && (
          <div className="flex justify-between">
            <span className="text-wolf-gray-light">Latency:</span>
            <span className={`font-mono-numbers ${
              health.latency_ms < 100 ? 'text-wolf-green' :
              health.latency_ms < 250 ? 'text-yellow-500' :
              'text-wolf-red'
            }`}>
              {health.latency_ms}ms
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
