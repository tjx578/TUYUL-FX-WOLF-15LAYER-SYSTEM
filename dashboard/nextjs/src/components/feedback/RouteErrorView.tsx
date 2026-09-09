"use client";

interface RouteErrorViewProps {
  title?: string;
  message?: string;
  reset?: () => void;
}

export default function RouteErrorView({
  title = "Unexpected error",
  message = "Something went wrong while rendering this route.",
  reset,
}: RouteErrorViewProps) {
  return (
    <div className="viewer-fallback">
      <div className="viewer-fallback-card">
        <h2>{title}</h2>
        <p>{message}</p>
        {reset ? (
          <button
            type="button"
            className="viewer-retry"
            onClick={() => reset()}
          >
            Retry
          </button>
        ) : null}
      </div>
    </div>
  );
}
