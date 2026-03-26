import axios from "axios";
import { bearerHeader } from "@/lib/auth";

export const apiClient = axios.create({
    baseURL: "",
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
