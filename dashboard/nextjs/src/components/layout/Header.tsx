"use client";

import { useAuthStore } from "@/store/useAuthStore";

export default function Header() {
  const user = useAuthStore((state) => state.user);

  return (
    <header className="mb-4 flex items-center justify-between rounded-2xl border border-white/10 bg-slate-900/60 px-4 py-3">
      <div>
        <div className="text-xs uppercase tracking-wider text-slate-400">Session</div>
        <div className="text-sm font-semibold text-white">{user?.email ?? "Unknown user"}</div>
      </div>
      <div className="text-xs text-slate-300">Role: {user?.role ?? "viewer"}</div>
    </header>
  );
}
