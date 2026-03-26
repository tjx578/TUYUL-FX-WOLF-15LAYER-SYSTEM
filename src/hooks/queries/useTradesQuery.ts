"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchTrades } from "@/services/tradeService";

export function useTradesQuery(accountId?: string, page = 1, pageSize = 20) {
  return useQuery({
    queryKey: ["trades", accountId, page, pageSize],
    queryFn: () => fetchTrades(accountId, page, pageSize),
  });
}
