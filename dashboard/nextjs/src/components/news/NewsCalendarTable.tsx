import type { CalendarEvent } from "@/types";

interface NewsCalendarTableProps {
  events: CalendarEvent[];
  title?: string;
}

export default function NewsCalendarTable({
  events,
  title = "Economic Calendar",
}: NewsCalendarTableProps) {
  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-950 p-4">
      <div className="mb-3 text-sm font-semibold text-neutral-200">{title}</div>

      {events.length === 0 ? (
        <div className="text-sm text-neutral-400">No events available.</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] text-sm">
            <thead>
              <tr className="border-b border-neutral-800 text-neutral-400">
                <th className="py-2 text-left font-medium">Time (UTC)</th>
                <th className="py-2 text-left font-medium">Currency</th>
                <th className="py-2 text-left font-medium">Impact</th>
                <th className="py-2 text-left font-medium">Event</th>
                <th className="py-2 text-left font-medium">Actual</th>
                <th className="py-2 text-left font-medium">Forecast</th>
                <th className="py-2 text-left font-medium">Previous</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr
                  key={event.id ?? event.canonical_id ?? `${event.currency}:${event.time}:${event.title ?? event.event ?? ""}`}
                  className="border-b border-neutral-900 align-top"
                >
                  <td className="py-2 pr-2 text-neutral-300">{event.time || "-"}</td>
                  <td className="py-2 pr-2 font-medium text-neutral-100">{event.currency || "-"}</td>
                  <td className="py-2 pr-2">
                    <span className="rounded border border-neutral-700 px-2 py-0.5 text-xs text-neutral-200">
                      {event.impact}
                    </span>
                  </td>
                  <td className="py-2 pr-2 text-neutral-200">{event.title ?? event.event ?? "-"}</td>
                  <td className="py-2 pr-2 text-neutral-300">{event.actual ?? "-"}</td>
                  <td className="py-2 pr-2 text-neutral-300">{event.forecast ?? "-"}</td>
                  <td className="py-2 pr-2 text-neutral-300">{event.previous ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
