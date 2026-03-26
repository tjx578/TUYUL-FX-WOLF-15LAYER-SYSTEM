import axios from "axios";
import { bearerHeader } from "@/lib/auth";

// Use the public API base URL when available (injected by next.config.ts env block).
// In the browser we use relative URLs when no explicit base is set so that
// Next.js rewrites handle the proxying transparently.
const _apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || "";

export const apiClient = axios.create({
    baseURL: _apiBase,
    headers: {
        "Content-Type": "application/json",
    },
    withCredentials: true,
    timeout: 15000,
});

apiClient.interceptors.request.use((config) => {
    const auth = bearerHeader();
    if (auth) {
        config.headers = config.headers ?? {};
        config.headers["Authorization"] = auth;
    }
    return config;
});
