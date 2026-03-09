import { Skeleton } from "@/components/primitives/Skeleton";

export default function RiskLoading() {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Skeleton className="h-56 w-full" />
      <Skeleton className="h-56 w-full" />
    </div>
  );
}
