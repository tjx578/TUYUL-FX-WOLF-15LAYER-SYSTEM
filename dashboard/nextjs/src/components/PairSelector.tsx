'use client';

import { usePairs } from '@/lib/api';

interface PairSelectorProps {
  selectedPair: string;
  onSelectPair: (pair: string) => void;
}

export default function PairSelector({ selectedPair, onSelectPair }: PairSelectorProps) {
  const { data: pairs, isLoading, error: isError } = usePairs();

  // Fallback pairs if API fails
  const defaultPairs = ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD'];
  const displayPairs = pairs?.map(p => p.symbol) || defaultPairs;

  return (
    <div className="bg-wolf-gray rounded-lg p-4 border border-wolf-gray-light">
      <div className="flex flex-wrap gap-2">
        {displayPairs.map((pair) => (
          <button
            key={pair}
            onClick={() => onSelectPair(pair)}
            className={`px-4 py-2 rounded-lg font-semibold transition-all ${
              selectedPair === pair
                ? 'bg-wolf-gold text-wolf-dark'
                : 'bg-wolf-darker text-white hover:bg-wolf-gray-light'
            }`}
          >
            {pair}
          </button>
        ))}
      </div>
      {isError && (
        <p className="text-xs text-wolf-red mt-2">
          ⚠️ Using default pairs (API unavailable)
        </p>
      )}
    </div>
  );
}
