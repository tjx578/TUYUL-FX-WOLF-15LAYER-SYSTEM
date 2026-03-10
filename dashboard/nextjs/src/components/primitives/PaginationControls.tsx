"use client";

interface Props {
  page: number;
  onPrev: () => void;
  onNext: () => void;
}

export default function PaginationControls({ page, onPrev, onNext }: Props) {
  return (
    <div className="flex items-center gap-2" role="navigation" aria-label="Pagination">
      <button
        type="button"
        onClick={onPrev}
        className="rounded-lg border border-white/20 px-3 py-1 text-sm"
        aria-label="Previous page"
      >
        Prev
      </button>
      <span className="text-sm text-slate-300">Page {page}</span>
      <button
        type="button"
        onClick={onNext}
        className="rounded-lg border border-white/20 px-3 py-1 text-sm"
        aria-label="Next page"
      >
        Next
      </button>
    </div>
  );
}
