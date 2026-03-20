"use client";

import RouteErrorView from "@/components/feedback/RouteErrorView";

export default function TradesError({ reset }: { reset: () => void }) {
  return (
    <RouteErrorView
      title="Trades failed to load"
      message="Unable to render trade data right now."
      reset={reset}
    />
  );
}
