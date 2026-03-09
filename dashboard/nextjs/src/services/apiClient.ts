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

if (!baseURL) {
  throw new Error(
    "Missing API base URL: set NEXT_PUBLIC_API_URL (or NEXT_PUBLIC_API_BASE_URL/INTERNAL_API_URL)."
  );
}

export const apiClient = axios.create({
  baseURL: baseURL.replace(/\/$/, ""),
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
