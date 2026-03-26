export default function UnauthorizedPage() {
  return (
    <main className="min-h-screen bg-[#030712] text-white flex items-center justify-center px-6">
      <div className="w-full max-w-xl rounded-3xl border border-white/10 bg-white/5 p-8 shadow-2xl backdrop-blur">
        <div className="inline-flex items-center rounded-full border border-amber-400/30 bg-amber-400/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-amber-200">
          Access required
        </div>
        <h1 className="mt-5 text-3xl font-semibold tracking-tight">Dashboard session not verified</h1>
        <p className="mt-3 text-sm leading-6 text-slate-300">
          This control surface is no longer open by default. Sign in through the configured
          dashboard auth flow or provide a valid session cookie before opening protected routes.
        </p>
        <div className="mt-6 rounded-2xl border border-cyan-400/20 bg-cyan-400/5 p-4 text-sm text-cyan-100">
          Expected auth source: <code className="font-mono">wolf15_session</code> cookie or an
          explicitly enabled development-owner fallback.
        </div>
      </div>
    </main>
  );
}
