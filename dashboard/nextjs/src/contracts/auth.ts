/**
 * Roles retained for compatibility with the core API.
 *
 * The deployed G4 visual service accepts only "viewer"; see viewerContract.ts.
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
  name?: string | null;
  scopes?: readonly string[];
  auth_method?: string;
}
