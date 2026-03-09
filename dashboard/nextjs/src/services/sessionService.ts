import { SessionUserSchema } from "@/schema/authSchema";
import { apiClient } from "./apiClient";

export async function refreshSession() {
  const { data } = await apiClient.post("/auth/refresh");
  return SessionUserSchema.parse(data);
}
