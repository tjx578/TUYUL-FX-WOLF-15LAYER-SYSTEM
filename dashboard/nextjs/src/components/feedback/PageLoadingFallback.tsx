import { Skeleton } from "@/components/primitives/Skeleton";

export function PageLoadingFallback() {
    return <Skeleton className="h-96 w-full" />;
}
