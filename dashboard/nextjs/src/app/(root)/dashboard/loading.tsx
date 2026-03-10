import { Skeleton } from "@/components/primitives/Skeleton";

export default function DashboardLoading() {
  return (
    <div className="grid gap-4">
      <Skeleton className="h-72 w-full" />
      <Skeleton className="h-40 w-full" />
    </div>
  );
}
