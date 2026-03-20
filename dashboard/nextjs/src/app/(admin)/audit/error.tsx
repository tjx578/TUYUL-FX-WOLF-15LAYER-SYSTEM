"use client";

import RouteErrorView from "@/components/feedback/RouteErrorView";

export default function AuditError({ reset }: { reset: () => void }) {
  return (
    <RouteErrorView
      title="Audit failed to load"
      message="Unable to render audit data right now."
      reset={reset}
    />
  );
}
