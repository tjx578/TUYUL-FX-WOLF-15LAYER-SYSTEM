"use client";

import RouteErrorView from "@/components/feedback/RouteErrorView";

export default function GlobalError({ reset }: { reset: () => void }) {
  return (
    <html lang="en">
      <body>
        <RouteErrorView
          title="Application error"
          message="The application encountered an unexpected error."
          reset={reset}
        />
      </body>
    </html>
  );
}
