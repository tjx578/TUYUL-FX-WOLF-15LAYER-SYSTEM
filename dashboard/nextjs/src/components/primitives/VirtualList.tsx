"use client";

import React, { useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";

interface VirtualListProps<T> {
  items: T[];
  rowHeight?: number;
  height?: number;
  renderRow: (item: T, index: number) => React.ReactNode;
}

// ── VirtualRow ────────────────────────────────────────────────
// Memoized wrapper so each row only re-renders when its item identity
// or index changes, not when sibling rows update.

interface VirtualRowProps<T> {
  item: T;
  index: number;
  size: number;
  start: number;
  renderRow: (item: T, index: number) => React.ReactNode;
}

const VirtualRow = React.memo(
  function VirtualRow<T>({ item, index, size, start, renderRow }: VirtualRowProps<T>) {
    return (
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: "100%",
          height: size,
          transform: `translateY(${start}px)`,
        }}
      >
        {renderRow(item, index)}
      </div>
    );
  },
  (prev, next) =>
    prev.item === next.item &&
    prev.index === next.index &&
    prev.size === next.size &&
    prev.start === next.start &&
    prev.renderRow === next.renderRow,
) as <T>(props: VirtualRowProps<T>) => React.ReactElement;

// ── VirtualList ───────────────────────────────────────────────

export function VirtualList<T>({
  items,
  rowHeight = 56,
  height = 360,
  renderRow,
}: VirtualListProps<T>) {
  const parentRef = useRef<HTMLDivElement | null>(null);

  const rowVirtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => rowHeight,
    overscan: 8,
  });

  return (
    <div ref={parentRef} style={{ height, overflow: "auto" }}>
      <div style={{ height: rowVirtualizer.getTotalSize(), position: "relative" }}>
        {rowVirtualizer.getVirtualItems().map((virtualItem) => (
          <VirtualRow
            key={virtualItem.key}
            item={items[virtualItem.index]}
            index={virtualItem.index}
            size={virtualItem.size}
            start={virtualItem.start}
            renderRow={renderRow}
          />
        ))}
      </div>
    </div>
  );
}
