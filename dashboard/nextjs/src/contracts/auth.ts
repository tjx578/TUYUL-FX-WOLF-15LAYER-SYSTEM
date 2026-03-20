export type UserRole =
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
