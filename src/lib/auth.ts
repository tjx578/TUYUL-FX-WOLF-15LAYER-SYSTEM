import type { UserRole } from "@/contracts/auth";

const TOKEN_KEY = "wolf15_token";
const IS_PRODUCTION = process.env.NODE_ENV === "production";

export const ADMIN_ROLES = ["risk_admin", "config_admin", "approver"] as const;

export function hasRole(
  role: UserRole | undefined,
  allowedRoles: readonly UserRole[]
): boolean {
  if (!role) return false;
  return allowedRoles.includes(role);
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  if (IS_PRODUCTION) return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  if (IS_PRODUCTION) {
    fetch("/api/set-session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
      credentials: "include",
    }).catch(() => {});
    return;
  }
  localStorage.setItem(TOKEN_KEY, token);
}

export function removeToken(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
}

export function getTransportToken(): string | null {
  return getToken();
}

export function bearerHeader(): string | undefined {
  const token = getTransportToken();
  if (token) return `Bearer ${token}`;
  return undefined;
}

export function scheduleRefresh(_token?: string): void {}
export function cancelRefresh(): void {}
export function clearWsTicketCache(): void {}
export async function fetchWsTicket(): Promise<string | null> {
  return getToken();
}
