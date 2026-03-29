import type { SessionUser, UserRole } from "@/contracts/auth";
import { hasRole } from "@/lib/auth";

/**
 * Owner-only auth model.
 *
 * This dashboard is a private owner control surface — NOT a public
 * multi-user product.  There is no login UI, no public-user session,
 * and no browser-facing API key flow.
 *
 * Every server component receives this fixed owner identity.
 * See docs/architecture/dashboard-control-surface.md — Auth Model.
 */
const OWNER_USER: SessionUser = {
  user_id: "owner",
  email: "owner@tuyulfx.com",
  role: "owner" as UserRole,
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
