"use client";

import RouteErrorView from "@/components/feedback/RouteErrorView";

export default function DashboardError({ reset }: { reset: () => void }) {
  return (
    <RouteErrorView
      title="Dashboard failed to load"
      message="Unable to render dashboard data right now."
      reset={reset}
    />
  );
}
