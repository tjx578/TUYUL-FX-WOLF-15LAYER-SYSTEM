/**
 * @deprecated wsService.ts is deprecated and will be deleted after Phase C migration.
 *
 * This file is a thin re-export shim that keeps existing imports compilable
 * while the real implementation lives in:
 *
 *   src/lib/realtime/realtimeClient.ts
 *
 * DO NOT add new imports from this file.
 * DO NOT add new logic here.
 * Migrate all callers to the domain hooks in src/lib/realtime/hooks/.
 */

export type { WsConnectionStatus, WsControls } from "@/lib/realtime/realtimeClient";
export { connectLiveUpdates } from "@/lib/realtime/realtimeClient";
