import type {
    CalendarEvent,
    CalendarDayResponse,
    CalendarUpcomingResponse,
    CalendarBlockerResponse,
    CalendarHealthResponse,
} from "@/types";
import { useApiQuery, API_ENDPOINTS, POLL_INTERVALS } from "@/shared/api/client";

export function useCalendarEvents(period = "today", impact?: string) {
    const params = new URLSearchParams();
    if (impact) params.set("impact", impact);
    const endpoint = period === "upcoming"
        ? `${API_ENDPOINTS.calendarUpcoming}?${params.toString()}`
        : `${API_ENDPOINTS.calendar}?${params.toString()}`;
    const { data, error, isLoading } = useApiQuery<CalendarDayResponse | CalendarUpcomingResponse | CalendarEvent[]>(
        endpoint,
        { refetchInterval: POLL_INTERVALS.calendar },
    );
    const raw = Array.isArray(data)
        ? data
        : Array.isArray(data?.events)
            ? data.events
            : [];

    const normalized = raw.map((item: CalendarEvent) => {
        const title = item.title ?? item.event ?? "";
        const eventId = item.id ?? item.canonical_id ?? `${item.currency}:${title}:${item.time}`;
        return {
            ...item,
            id: eventId,
            event: item.event ?? title,
            title,
        } as CalendarEvent;
    });

    return { data: normalized as CalendarEvent[], isLoading, isError: !!error, error };
}

export function useCalendarBlocker(symbol?: string) {
    const query = symbol ? `?symbol=${encodeURIComponent(symbol)}` : "";
    const { data, error, isLoading, mutate } = useApiQuery<CalendarBlockerResponse>(
        `${API_ENDPOINTS.calendarBlocker}${query}`,
    );
    return { data, isLoading, isError: !!error, error, mutate };
}

export function useCalendarSourceHealth() {
    const { data, error, isLoading, mutate } = useApiQuery<CalendarHealthResponse>(
        API_ENDPOINTS.calendarHealth,
    );
    return { data, isLoading, isError: !!error, error, mutate };
}
