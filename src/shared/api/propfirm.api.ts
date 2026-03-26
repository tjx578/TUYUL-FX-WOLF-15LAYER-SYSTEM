import type { PropFirmPhase, PropFirmStatus } from "@/types";
import { useApiQuery, fetcher, API_ENDPOINTS } from "@/shared/api/client";

export function usePropFirmPhase(accountId: string) {
    const { data, error, isLoading } = useApiQuery<PropFirmPhase>(
        accountId ? API_ENDPOINTS.propFirmPhase(accountId) : null,
    );
    return { data, isLoading, isError: !!error, error };
}

export function usePropFirmStatus(accountId: string) {
    const { data, error, isLoading } = useApiQuery<PropFirmStatus>(
        accountId ? API_ENDPOINTS.propFirmStatus(accountId) : null,
    );
    return { data, isLoading, isError: !!error, error };
}

export async function fetchPropFirms() {
    return fetcher("/api/v1/prop-firm/firms");
}

export async function fetchPropFirmPrograms(firm_code: string) {
    return fetcher(`/api/v1/prop-firm/firms/${firm_code}/programs`);
}

export async function fetchPropFirmRules(firm_code: string, program_code: string, phase: string = "funded") {
    return fetcher(`/api/v1/prop-firm/firms/${firm_code}/programs/${program_code}/rules?phase=${phase}`);
}
