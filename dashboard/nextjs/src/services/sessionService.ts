import { SessionUserSchema } from "@/schema/authSchema";
import { AUTH_REFRESH } from "@/lib/endpoints";
import { apiClient } from "./apiClient";

export async function refreshSession() {
  const { data } = await apiClient.post(AUTH_REFRESH);
  return SessionUserSchema.parse(data);
}
