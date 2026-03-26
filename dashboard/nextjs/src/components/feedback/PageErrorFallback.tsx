"use client";

import RouteErrorView from "@/components/feedback/RouteErrorView";

export function PageErrorFallback({ reset }: { reset: () => void }) {
    return (
        <RouteErrorView
            title="Page failed to load"
            message="Unable to render data right now."
            reset={reset}
        />
    );
}
