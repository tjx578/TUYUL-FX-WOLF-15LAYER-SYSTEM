"use client";

import { useEffect, useRef } from "react";
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
  const syncingFromUrlRef = useRef(false);

  // URL → State: parse query params when URL changes externally
  useEffect(() => {
    syncingFromUrlRef.current = true;
    const parsed = parseTableQuery(new URLSearchParams(searchParams.toString()));
    options.setState(parsed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  // State → URL: push state to URL when state changes from user interaction
  useEffect(() => {
    if (syncingFromUrlRef.current) {
      syncingFromUrlRef.current = false;
      return;
    }
    const nextParams = toTableQueryParams(options.state).toString();
    const href = nextParams ? `${pathname}?${nextParams}` : pathname;
    router.replace(href, { scroll: false });
    // searchParams intentionally excluded — this effect reacts to state only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options.state, pathname, router]);
}
