"use client";

import RouteErrorView from "@/components/feedback/RouteErrorView";

export default function Error({ reset }: { reset: () => void }) {
    return (
        <RouteErrorView
            title="Signal Board failed to load"
            message="Unable to render data right now."
            reset={reset}
        />
    );
}
