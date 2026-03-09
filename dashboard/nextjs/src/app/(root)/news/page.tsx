"use client";

import { useCalendarEvents } from "@/lib/api";
import PageComplianceBanner from "@/components/feedback/PageComplianceBanner";
import type { CalendarEvent } from "@/types";

export default function NewsPage() {
  const { data, isLoading } = useCalendarEvents("today", "HIGH");

  if (isLoading) return <div>Loading calendar...</div>;

  return (
    <div className="flex flex-col gap-4">
      <PageComplianceBanner page="news" />

      <div className="rounded-xl border p-4">
        <div className="font-semibold mb-2">News Calendar</div>
        <table className="w-full text-sm">
          <thead>
            <tr>
              <th align="left">Time</th>
              <th align="left">Currency</th>
              <th align="left">Impact</th>
              <th align="left">Event</th>
            </tr>
          </thead>
          <tbody>
            {data?.map((e: CalendarEvent) => (
              <tr key={e.id}>
                <td>{e.time}</td>
                <td>{e.currency}</td>
                <td>{e.impact}</td>
                <td>{e.event}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
