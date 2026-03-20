"use client";

import RouteErrorView from "@/components/feedback/RouteErrorView";

export default function RiskError({ reset }: { reset: () => void }) {
  return (
    <RouteErrorView
      title="Risk monitor failed to load"
      message="Unable to render risk data right now."
      reset={reset}
    />
  );
}
