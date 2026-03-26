import type { SessionUser, UserRole } from "@/contracts/auth";
import { hasRole } from "@/lib/auth";

// Owner is the sole user — no login, no API key, no cookie required.
// The dashboard is unrestricted: every server component receives this default user.
const OWNER_USER: SessionUser = {
  user_id: "owner",
  email: "owner@tuyulfx.com",
  role: "risk_admin" as UserRole,
  name: "TUYUL FX Owner",
};

export async function getVerifiedSessionUser(): Promise<SessionUser | null> {
  return OWNER_USER;
}

export async function requireVerifiedSession(
  allowedRoles?: readonly UserRole[]
): Promise<SessionUser> {
  if (allowedRoles?.length && !hasRole(OWNER_USER.role, allowedRoles)) {
    throw new Error("Forbidden: role is not allowed for this route");
  }
  return OWNER_USER;
}
