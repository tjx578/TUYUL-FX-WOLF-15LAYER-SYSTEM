import { useToastStore, type ToastLevel } from "@/store/useToastStore";

/**
 * Imperative push helper — safe to call from non-component code
 * (event handlers, async callbacks, etc.).
 * Wraps the existing Zustand toast store.
 */
export function pushToast(input: {
    level: ToastLevel;
    title: string;
    message?: string;
}): void {
    useToastStore.getState().push({
        title: input.title,
        description: input.message,
        level: input.level,
    });
}
