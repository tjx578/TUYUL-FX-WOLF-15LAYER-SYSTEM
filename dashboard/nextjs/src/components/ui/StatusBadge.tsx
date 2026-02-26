// ============================================================
// TUYUL FX Wolf-15 — Status Badge
// Institutional verdict / state badge component.
// ============================================================

interface Props {
  type: "execute" | "hold" | "no-trade" | "abort";
  label: string;
}

const styles: Record<Props["type"], string> = {
  execute:    "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  hold:       "bg-amber-500/10 text-amber-400 border-amber-500/20",
  "no-trade": "bg-red-500/10 text-red-400 border-red-500/20",
  abort:      "bg-red-600/15 text-red-400 border-red-600/30",
};

export default function StatusBadge({ type, label }: Props) {
  const base = "inline-flex items-center px-3 py-1 text-xs tracking-wider uppercase rounded-full border font-medium";

  return (
    <span className={`${base} ${styles[type]}`}>{label}</span>
  );
}
