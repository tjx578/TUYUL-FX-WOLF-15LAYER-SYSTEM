import { z } from "zod";
import { apiClient } from "./apiClient";

export const AuditEntrySchema = z.object({
  id: z.string().min(1),
  timestamp: z.string().datetime({ offset: true }),
  action: z.string().min(1),
  actor: z.string().min(1).optional(),
  metadata: z.unknown().optional(),
});

export const AuditEntryListSchema = z.array(AuditEntrySchema);

export type AuditEntry = z.infer<typeof AuditEntrySchema>;

export async function fetchAuditLog(limit = 50) {
  const response = await apiClient.get("/api/v1/audit", {
    params: { limit },
  });

  return AuditEntryListSchema.parse(response.data);
}

export async function fetchAuditEntries(page = 1, pageSize = 20) {
  const response = await apiClient.get("/api/v1/audit", {
    params: {
      page,
      page_size: pageSize,
    },
  });

  return AuditEntryListSchema.parse(response.data);
}
