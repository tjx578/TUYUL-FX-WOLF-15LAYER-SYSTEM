"use client";

import RouteErrorView from "@/components/feedback/RouteErrorView";

export default function AccountsError({ reset }: { reset: () => void }) {
  return (
    <RouteErrorView
      title="Accounts failed to load"
      message="Unable to render account data right now."
      reset={reset}
    />
  );
}
