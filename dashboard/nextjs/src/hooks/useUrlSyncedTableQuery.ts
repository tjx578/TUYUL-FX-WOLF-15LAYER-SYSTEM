"use client";

import { useEffect } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { TableQueryState } from "@/contracts/queryState";
import { parseTableQuery, toTableQueryParams } from "@/lib/queryParams";

interface UseUrlSyncedTableQueryOptions {
  state: TableQueryState;
  setState: (next: Partial<TableQueryState>) => void;
}

export function useUrlSyncedTableQuery(options: UseUrlSyncedTableQueryOptions) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => {
    const parsed = parseTableQuery(new URLSearchParams(searchParams.toString()));
    options.setState(parsed);
    // Parse only when URL changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  useEffect(() => {
    const nextParams = toTableQueryParams(options.state).toString();
    const currentParams = searchParams.toString();
    if (nextParams !== currentParams) {
      const href = nextParams ? `${pathname}?${nextParams}` : pathname;
      router.replace(href);
    }
  }, [options.state, pathname, router, searchParams]);
}
