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
    <div className="flex min-h-[50vh] items-center justify-center">
      <div className="w-full max-w-xl rounded-2xl border border-white/10 bg-slate-900/80 p-6 text-white">
        <h2 className="text-xl font-semibold">{title}</h2>
        <p className="mt-2 text-sm text-slate-300">{message}</p>
        {reset ? (
          <button
            type="button"
            className="mt-4 rounded-lg border border-white/20 px-4 py-2 text-sm"
            onClick={() => reset()}
          >
            Retry
          </button>
        ) : null}
      </div>
    </div>
  );
}
