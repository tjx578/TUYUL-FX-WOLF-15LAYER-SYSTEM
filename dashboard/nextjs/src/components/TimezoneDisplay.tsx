'use client';

import { useEffect, useState } from 'react';
import { Clock } from 'lucide-react';
import { getCurrentLocalTime, getCurrentUTCTime } from '@/lib/timezone';

export default function TimezoneDisplay() {
  const [utcTime, setUtcTime] = useState<string>('');
  const [localTime, setLocalTime] = useState<string>('');

  useEffect(() => {
    const updateTimes = () => {
      setUtcTime(getCurrentUTCTime());
      setLocalTime(getCurrentLocalTime());
    };

    updateTimes();
    const interval = setInterval(updateTimes, 1000);

    return () => clearInterval(interval);
  }, []);

  return (
    <div className="bg-wolf-gray rounded-lg p-3 border border-wolf-gray-light">
      <div className="flex items-center gap-2 mb-2">
        <Clock className="w-4 h-4 text-wolf-gold" />
        <span className="text-xs font-semibold text-wolf-gold">TIME</span>
      </div>
      <div className="space-y-1 text-xs font-mono-numbers">
        <div>
          <span className="text-wolf-gray-light">UTC:</span>{' '}
          <span className="text-white">{utcTime || 'Loading...'}</span>
        </div>
        <div>
          <span className="text-wolf-gray-light">GMT+8:</span>{' '}
          <span className="text-white">{localTime || 'Loading...'}</span>
        </div>
      </div>
    </div>
  );
}
