"use client";

import RouteErrorView from "@/components/feedback/RouteErrorView";

export default function MainError({ reset }: { reset: () => void }) {
  return (
    <RouteErrorView
      title="Page failed to load"
      message="Unable to render data right now."
      reset={reset}
    />
  );
}
