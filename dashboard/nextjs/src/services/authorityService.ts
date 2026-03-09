import { z } from "zod";
import { apiClient } from "./apiClient";

export const AuthoritySurfaceSchema = z.object({
  action: z.string().min(1),
  allowed: z.boolean(),
  reason: z.string().min(1).optional(),
  code: z.string().min(1).optional(),
});

export type AuthoritySurface = z.infer<typeof AuthoritySurfaceSchema>;

export async function fetchAuthoritySurface(action: string) {
  const response = await apiClient.get("/api/v1/authority/surface", {
    params: { action },
  });

  return AuthoritySurfaceSchema.parse(response.data);
}
