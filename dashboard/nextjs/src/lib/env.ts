/**
 * Centralized env access for NEXT_PUBLIC_ vars.
 * process.env.NEXT_PUBLIC_* is replaced at build time by Next.js.
 */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "";