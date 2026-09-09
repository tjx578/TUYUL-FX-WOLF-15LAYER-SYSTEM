import { VIEWER_PROXY_PATHS } from "@/lib/viewerContract";

/** Exact G4 viewer boundary. Prefix matching is deliberately forbidden. */
export const READ_ONLY_PATHS: readonly string[] = VIEWER_PROXY_PATHS;

export function isAllowlistedReadPath(path: string): boolean {
  if (
    !path ||
    path.startsWith("/") ||
    path.endsWith("/") ||
    path.includes("\\") ||
    path.includes("%") ||
    path.includes("?") ||
    path.includes("#")
  ) {
    return false;
  }

  const segments = path.split("/");
  if (segments.some((segment) => !segment || segment === "." || segment === "..")) {
    return false;
  }

  return READ_ONLY_PATHS.includes(path);
}
