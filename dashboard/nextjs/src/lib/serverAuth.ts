import { headers } from "next/headers";
import { redirect } from "next/navigation";
import type { SessionUser, UserRole } from "@/contracts/auth";
import { SessionUserSchema } from "@/schema/authSchema";

function getApiBase(): string | null {
  const base = process.env.INTERNAL_API_URL || process.env.NEXT_PUBLIC_API_URL;
  if (!base || base.trim() === "") {
    return null;
  }
  return base.replace(/\/$/, "");
}

function toRedirectPath(): string {
  return "/";
}

export async function getVerifiedSessionUser(): Promise<SessionUser | null> {
  const apiBase = getApiBase();
  if (!apiBase) {
    return null;
  }

  const h = await headers();
  const authHeader = h.get("authorization");
  const cookieHeader = h.get("cookie");

  try {
    const response = await fetch(`${apiBase}/auth/session`, {
      method: "GET",
      headers: {
        ...(authHeader ? { authorization: authHeader } : {}),
        ...(cookieHeader ? { cookie: cookieHeader } : {}),
      },
      cache: "no-store",
    });

    if (!response.ok) {
      return null;
    }

    const raw = await response.json();
    return SessionUserSchema.parse(raw);
  } catch {
    return null;
  }
}

export async function requireVerifiedSession(
  allowedRoles?: readonly UserRole[]
): Promise<SessionUser> {
  const session = await getVerifiedSessionUser();

  if (!session) {
    redirect(toRedirectPath());
  }

  if (allowedRoles && !allowedRoles.includes(session.role)) {
    redirect(toRedirectPath());
  }

  return session;
}
