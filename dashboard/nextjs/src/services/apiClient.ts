import axios, { AxiosError } from "axios";

export interface ApiErrorPayload {
  code?: string;
  message: string;
  details?: unknown;
}

const baseURL =
  process.env.NEXT_PUBLIC_API_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  process.env.INTERNAL_API_URL;

const resolvedBaseURL = (baseURL && baseURL.trim()) || "http://localhost:8000";
if (!baseURL || baseURL.trim() === "") {
  console.warn(
    "[apiClient] Missing API base URL env; falling back to http://localhost:8000. " +
      "Set NEXT_PUBLIC_API_URL or NEXT_PUBLIC_API_BASE_URL in production."
  );
}

export const apiClient = axios.create({
  baseURL: resolvedBaseURL.replace(/\/$/, ""),
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
