export default function NotFound() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 text-white">
      <div className="rounded-2xl border border-white/10 bg-slate-900 p-8">
        <h1 className="text-2xl font-semibold">404</h1>
        <p className="mt-2 text-sm text-slate-400">Route not found.</p>
      </div>
    </div>
  );
}
