"use client";

import { useSearchParams } from "next/navigation";
import { useMemo } from "react";
import { parseLifecycleNavigationContext } from "@/shared/contracts/lifecycleNavigation";

export function useLifecycleNavigationContext() {
    const searchParams = useSearchParams();

    return useMemo(() => {
        return parseLifecycleNavigationContext(searchParams);
    }, [searchParams]);
}
