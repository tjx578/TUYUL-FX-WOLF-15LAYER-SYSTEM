import { headers, cookies } from "next/headers";
import { redirect } from "next/navigation";
import type { SessionUser, UserRole } from "@/contracts/auth";

const SESSION_COOKIE = "wolf15_session";
const DEV_OWNER_ENABLED =
  process.env.NODE_ENV !== "production" &&
  process.env.DASHBOARD_ALLOW_DEV_OWNER === "true";

const DEV_OWNER_USER: SessionUser = {
  user_id: "owner",
  email: "owner@tuyulfx.com",
  role: "risk_admin" as UserRole,
  name: "TUYUL FX Owner",
};

function isAllowedRole(
  role: UserRole,
  allowedRoles?: readonly UserRole[],
): boolean {
  return !allowedRoles?.length || allowedRoles.includes(role);
}

function safeDecodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const [, payload] = token.split(".");
    if (!payload) return null;
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    const decoded = Buffer.from(normalized, "base64").toString("utf-8");
    return JSON.parse(decoded) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function coerceRole(value: unknown): UserRole {
  switch (value) {
    case "viewer":
    case "operator":
    case "risk_admin":
    case "config_admin":
    case "approver":
      return value;
    default:
      return "viewer";
  }
}

function userFromToken(token: string): SessionUser | null {
  const payload = safeDecodeJwtPayload(token);
  if (!payload) {
    return null;
  }

  const userId =
    typeof payload.sub === "string"
      ? payload.sub
      : typeof payload.user_id === "string"
        ? payload.user_id
        : null;

  const email = typeof payload.email === "string" ? payload.email : null;
  if (!userId || !email) {
    return null;
  }

  return {
    user_id: userId,
    email,
    role: coerceRole(payload.role),
    name: typeof payload.name === "string" ? payload.name : undefined,
  };
}

async function resolveSessionUser(): Promise<SessionUser | null> {
  const cookieStore = await cookies();
  const headerStore = await headers();

  const cookieToken = cookieStore.get(SESSION_COOKIE)?.value?.trim();
  const authHeader = headerStore.get("authorization")?.trim();
  const bearerToken = authHeader?.match(/^Bearer\s+(.+)$/i)?.[1]?.trim();

  const fromCookie = cookieToken ? userFromToken(cookieToken) : null;
  if (fromCookie) {
    return fromCookie;
  }

  const fromBearer = bearerToken ? userFromToken(bearerToken) : null;
  if (fromBearer) {
    return fromBearer;
  }

  if (DEV_OWNER_ENABLED) {
    return DEV_OWNER_USER;
  }

  return null;
}

export async function getVerifiedSessionUser(): Promise<SessionUser | null> {
  return resolveSessionUser();
}

export async function requireVerifiedSession(
  allowedRoles?: readonly UserRole[],
): Promise<SessionUser> {
  const user = await resolveSessionUser();

  if (!user) {
    redirect("/unauthorized");
  }

  if (!isAllowedRole(user.role, allowedRoles)) {
    redirect("/unauthorized?reason=role");
  }

  return user;
}
