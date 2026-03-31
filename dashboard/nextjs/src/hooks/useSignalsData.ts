"use client";

import { useMemo, useState } from "react";
import { signalsMock } from "@/lib/mock/signals";

export function useSignalsData() {
  const [selectedId, setSelectedId] = useState<string | null>(signalsMock.items[0]?.id ?? null);
  const cards = signalsMock.cards;
  const items = useMemo(() => signalsMock.items, []);

  function openTakeFlow(id: string) {
    // TODO: replace with modal + POST /take-signal via adapter
    alert(`Take Signal ${id} -> replace with POST /take-signal`);
    setSelectedId(id);
  }

  return { cards, items, selectedId, setSelectedId, openTakeFlow };
}
