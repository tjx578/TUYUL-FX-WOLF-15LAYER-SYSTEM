import type { SessionUser, UserRole } from "@/contracts/auth";
import { hasRole } from "@/lib/auth";

/**
 * Owner-only auth model — explicit mode.
 *
 * DASHBOARD_MODE must be "owner" (the only supported mode).
 * This dashboard is a private owner control surface — NOT a public
 * multi-user product.  There is no login UI, no public-user session,
 * and no browser-facing API key flow.
 *
 * The mode is validated at first use.  If the env var is missing or
 * set to an unsupported value, the guard throws immediately — no
 * implicit bypass, no silent fallback.
 *
 * See docs/architecture/dashboard-control-surface.md — Auth Model.
 */

const SUPPORTED_MODES = ["owner"] as const;
type DashboardMode = (typeof SUPPORTED_MODES)[number];

function validateDashboardMode(): DashboardMode {
  const raw = (process.env.DASHBOARD_MODE ?? "").trim().toLowerCase();
  if (!raw) {
    throw new Error(
      "DASHBOARD_MODE env var is not set. " +
      "Set DASHBOARD_MODE=owner for the owner-only control surface.",
    );
  }
  if (!SUPPORTED_MODES.includes(raw as DashboardMode)) {
    throw new Error(
      `DASHBOARD_MODE="${raw}" is not supported. ` +
      `Supported modes: ${SUPPORTED_MODES.join(", ")}.`,
    );
  }
  return raw as DashboardMode;
}

let _validatedMode: DashboardMode | null = null;

function ensureOwnerMode(): DashboardMode {
  if (_validatedMode === null) {
    _validatedMode = validateDashboardMode();
  }
  return _validatedMode;
}

const OWNER_USER: SessionUser = {
  user_id: "owner",
  email: "owner@tuyulfx.com",
  role: "owner" as UserRole,
  name: "TUYUL FX Owner",
};

export async function getVerifiedSessionUser(): Promise<SessionUser | null> {
  ensureOwnerMode();
  return OWNER_USER;
}

export async function requireVerifiedSession(
  allowedRoles?: readonly UserRole[],
): Promise<SessionUser> {
  ensureOwnerMode();
  if (allowedRoles?.length && !hasRole(OWNER_USER.role, allowedRoles)) {
    throw new Error("Forbidden: role is not allowed for this route");
  }
  return OWNER_USER;
}
