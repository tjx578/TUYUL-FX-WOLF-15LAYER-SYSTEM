import type { CalendarEvent } from "@/types";

interface HeatmapCell {
  hour: number;
  score: number;
  high: number;
  medium: number;
  low: number;
}

interface NewsHeatmapProps {
  events: CalendarEvent[];
}

function toHour(event: CalendarEvent): number | null {
  const raw = event.time?.trim();
  if (!raw) return null;
  const match = raw.match(/^(\d{1,2}):(\d{2})/);
  if (!match) return null;
  const hour = Number(match[1]);
  return Number.isFinite(hour) && hour >= 0 && hour <= 23 ? hour : null;
}

function buildCells(events: CalendarEvent[]): HeatmapCell[] {
  const base = Array.from({ length: 24 }, (_, hour) => ({
    hour,
    score: 0,
    high: 0,
    medium: 0,
    low: 0,
  }));

  for (const event of events) {
    const hour = toHour(event);
    if (hour === null) continue;

    if (event.impact === "HIGH") {
      base[hour].high += 1;
      base[hour].score += 3;
    } else if (event.impact === "MEDIUM") {
      base[hour].medium += 1;
      base[hour].score += 2;
    } else {
      base[hour].low += 1;
      base[hour].score += 1;
    }
  }

  return base;
}

function cellClass(score: number): string {
  if (score >= 6) return "bg-red-500/70";
  if (score >= 4) return "bg-amber-500/70";
  if (score >= 2) return "bg-lime-500/60";
  if (score >= 1) return "bg-cyan-500/55";
  return "bg-neutral-900";
}

export default function NewsHeatmap({ events }: NewsHeatmapProps) {
  const cells = buildCells(events);

  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-950 p-4">
      <div className="mb-3 text-sm font-semibold text-neutral-200">24h Impact Heatmap</div>
      <div className="grid grid-cols-6 gap-2 sm:grid-cols-8 md:grid-cols-12">
        {cells.map((cell) => (
          <div
            key={cell.hour}
            className={`rounded border border-neutral-800 p-2 ${cellClass(cell.score)}`}
            title={`UTC ${cell.hour.toString().padStart(2, "0")}:00 | high=${cell.high}, medium=${cell.medium}, low=${cell.low}`}
          >
            <div className="text-xs font-semibold text-neutral-100">
              {cell.hour.toString().padStart(2, "0")}
            </div>
            <div className="text-[11px] text-neutral-200">
              H{cell.high} M{cell.medium} L{cell.low}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
