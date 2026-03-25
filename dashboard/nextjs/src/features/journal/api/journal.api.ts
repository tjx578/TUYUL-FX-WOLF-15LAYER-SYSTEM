import type { DailyJournal, JournalMetrics } from "@/types";
import { useApiQuery } from "@/shared/api/client";

export function useJournalToday() {
    const { data, error, isLoading } = useApiQuery<DailyJournal>(
        "/api/v1/journal/today",
    );
    return { data, isLoading, isError: !!error, error };
}

export function useJournalWeekly() {
    const { data, error, isLoading } = useApiQuery<DailyJournal[]>(
        "/api/v1/journal/weekly",
    );
    return { data, isLoading, isError: !!error, error };
}

export function useJournalMetrics() {
    const { data, error, isLoading } = useApiQuery<JournalMetrics>(
        "/api/v1/journal/metrics",
    );
    return { data, isLoading, isError: !!error, error };
}
