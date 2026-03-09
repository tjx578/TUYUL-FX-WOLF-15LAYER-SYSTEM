"use client";

import { useEffect } from "react";
import { useToastStore } from "@/store/useToastStore";

const AUTO_DISMISS_MS = 3500;

export default function ToastViewport() {
  const toasts = useToastStore((state) => state.toasts);
  const dismiss = useToastStore((state) => state.dismiss);

  useEffect(() => {
    if (toasts.length === 0) {
      return;
    }

    const timers = toasts.map((toast) =>
      setTimeout(() => {
        dismiss(toast.id);
      }, AUTO_DISMISS_MS)
    );

    return () => {
      timers.forEach((timer) => clearTimeout(timer));
    };
  }, [dismiss, toasts]);

  if (toasts.length === 0) {
    return null;
  }

  return (
    <div className="fixed right-4 top-4 z-[100] flex w-[min(420px,90vw)] flex-col gap-2">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className="rounded-xl border border-white/10 bg-slate-900/95 px-4 py-3 text-sm text-white shadow-2xl"
        >
          <div className="font-semibold">{toast.title}</div>
          {toast.description ? (
            <p className="mt-1 text-xs text-slate-300">{toast.description}</p>
          ) : null}
        </div>
      ))}
    </div>
  );
}
