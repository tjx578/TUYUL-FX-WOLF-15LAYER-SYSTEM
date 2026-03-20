"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchAuditEntries } from "@/services/auditService";

export function useAuditQuery(page = 1, pageSize = 20) {
  return useQuery({
    queryKey: ["audit", page, pageSize],
    queryFn: () => fetchAuditEntries(page, pageSize),
  });
}
