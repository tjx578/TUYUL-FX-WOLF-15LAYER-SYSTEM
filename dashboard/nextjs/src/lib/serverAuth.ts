import type { SessionUser, UserRole } from "@/contracts/auth";

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
  _allowedRoles?: readonly UserRole[]
): Promise<SessionUser> {
  return OWNER_USER;
}
