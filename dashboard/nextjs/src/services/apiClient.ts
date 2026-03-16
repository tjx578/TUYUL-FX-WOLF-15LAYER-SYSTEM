import axios, { AxiosError } from "axios";
import { bearerHeader } from "@/lib/auth";

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
  withCredentials: true,
  timeout: 15000,
});

// Attach JWT (or fallback API key) from the unified auth module on every request.
// Single source of truth: lib/auth.ts — reads localStorage("wolf15_token")
// then falls back to NEXT_PUBLIC_API_KEY env var.
apiClient.interceptors.request.use((config) => {
  const auth = bearerHeader();
  if (auth) {
    config.headers = config.headers ?? {};
    config.headers["Authorization"] = auth;
  }
  return config;
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
