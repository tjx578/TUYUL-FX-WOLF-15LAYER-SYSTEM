"use client";

import type { PropsWithChildren } from "react";
import type { UserRole } from "@/contracts/auth";
import { hasRole } from "@/lib/auth";
import { useAuthStore } from "@/store/useAuthStore";

interface RequireRoleProps extends PropsWithChildren {
  allowedRoles: readonly UserRole[];
  fallback?: React.ReactNode;
}

export default function RequireRole({
  allowedRoles,
  fallback = null,
  children,
}: RequireRoleProps) {
  const user = useAuthStore((state) => state.user);
  const loading = useAuthStore((state) => state.loading);

  if (loading) {
    return null;
  }

  if (!hasRole(user?.role, allowedRoles)) {
    return <>{fallback}</>;
  }

  return <>{children}</>;
}
