"use client";

interface Props {
  search?: string;
  onSearchChange: (value: string) => void;
  sortBy?: string;
  onSortByChange?: (value: string) => void;
}

export default function TableToolbar({
  search,
  onSearchChange,
  sortBy,
  onSortByChange,
}: Props) {
  return (
    <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
      <input
        aria-label="Search table"
        value={search ?? ""}
        onChange={(e) => onSearchChange(e.target.value)}
        className="rounded-lg border border-white/20 bg-slate-900 px-3 py-2 text-sm text-white"
        placeholder="Search..."
      />
      {onSortByChange ? (
        <input
          aria-label="Sort by"
          value={sortBy ?? ""}
          onChange={(e) => onSortByChange(e.target.value)}
          className="rounded-lg border border-white/20 bg-slate-900 px-3 py-2 text-sm text-white"
          placeholder="Sort by field"
        />
      ) : null}
    </div>
  );
}
