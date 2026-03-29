/**
 * Auth model: owner-only.
 *
 * The dashboard is a private owner control surface.
 * "owner" is the canonical role for the sole operator.
 * Legacy roles (viewer, operator, risk_admin, config_admin, approver)
 * are retained for backward compatibility with existing JWTs.
 */
export type UserRole =
  | "owner"
  | "viewer"
  | "operator"
  | "risk_admin"
  | "config_admin"
  | "approver";

export interface SessionUser {
  user_id: string;
  email: string;
  role: UserRole;
  name?: string;
}
