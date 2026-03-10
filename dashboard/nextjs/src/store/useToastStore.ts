import { create } from "zustand";

export type ToastLevel = "success" | "info" | "warning" | "error";

export interface ToastMessage {
  id: string;
  title: string;
  description?: string;
  level: ToastLevel;
  createdAt: number;
}

interface ToastStore {
  toasts: ToastMessage[];
  push: (toast: Omit<ToastMessage, "id" | "createdAt">) => string;
  dismiss: (id: string) => void;
  clear: () => void;
}

export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],
  push: (toast) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    set((state) => ({
      toasts: [
        ...state.toasts,
        {
          ...toast,
          id,
          createdAt: Date.now(),
        },
      ],
    }));
    return id;
  },
  dismiss: (id) =>
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id),
    })),
  clear: () => set({ toasts: [] }),
}));
