'use client';

/**
 * Journal page — decision audit trail (J1–J4).
 */

import JournalView from '@/components/JournalView';

export default function JournalPage() {
  return (
    <div className="p-4 md:p-6">
      <div className="max-w-7xl mx-auto space-y-4">
        <header>
          <h1 className="text-2xl font-bold text-wolf-gold">Journal</h1>
          <p className="text-gray-500 text-xs">
            Immutable decision audit trail — J1 Context | J2 Decision | J3 Execution | J4 Reflection
          </p>
        </header>

        <JournalView />
      </div>
    </div>
  );
}
