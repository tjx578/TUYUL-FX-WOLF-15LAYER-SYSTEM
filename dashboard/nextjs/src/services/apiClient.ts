import axios, { AxiosError } from "axios";
import { bearerHeader } from "@/lib/auth";
import { getRestPrefix } from "@/lib/env";

export interface ApiErrorPayload {
  code?: string;
  message: string;
  details?: unknown;
}

// P4 consolidation: baseURL is always "/api/proxy" on the client.
// All REST calls go through the runtime proxy route handler which
// reads INTERNAL_API_URL at request time.
export const apiClient = axios.create({
  baseURL: getRestPrefix(),
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
