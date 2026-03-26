"use client";

import RouteErrorView from "@/components/feedback/RouteErrorView";

export default function ControlError({ reset }: { reset: () => void }) {
    return (
        <RouteErrorView
            title="Control routes failed to load"
            message="Unable to render control data right now."
            reset={reset}
        />
    );
}