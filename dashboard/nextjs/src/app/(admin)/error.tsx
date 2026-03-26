"use client";

import RouteErrorView from "@/components/feedback/RouteErrorView";

export default function AdminError({ reset }: { reset: () => void }) {
    return (
        <RouteErrorView
            title="Admin routes failed to load"
            message="Unable to render admin data right now."
            reset={reset}
        />
    );
}