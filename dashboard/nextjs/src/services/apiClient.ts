import axios, { AxiosError } from "axios";

export interface ApiErrorPayload {
  code?: string;
  message: string;
  details?: unknown;
}

// Use an empty baseURL so all requests are sent as relative paths (e.g. /api/v1/trades).
// Next.js rewrites in next.config.js proxy those paths to the real backend using
// INTERNAL_API_URL (server-side only), so no NEXT_PUBLIC_* build-time var is needed
// in the browser bundle.
export const apiClient = axios.create({
  baseURL: "",
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 15000,
});

export function toApiErrorPayload(error: unknown): ApiErrorPayload {
  if (axios.isAxiosError(error)) {
    const axiosError = error as AxiosError<{ code?: string; message?: string; details?: unknown }>;
    const responsePayload = axiosError.response?.data;
    return {
      code: responsePayload?.code,
      message: responsePayload?.message || axiosError.message || "Request failed",
      details: responsePayload?.details,
    };
  }

  return {
    message: error instanceof Error ? error.message : "Unknown error",
  };
}
