export default function AuditPage() {
  return (
    <div className="rounded-2xl border border-white/10 bg-slate-900/70 p-6">
      <h1 className="text-lg font-semibold text-white">Audit Console</h1>
      <p className="mt-2 text-sm text-slate-300">Admin audit route is protected by server auth guards.</p>
    </div>
  );
}
