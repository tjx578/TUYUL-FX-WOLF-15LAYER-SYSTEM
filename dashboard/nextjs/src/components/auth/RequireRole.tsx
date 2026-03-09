"use client";

import React from "react";
import type { PropsWithChildren, ReactNode } from "react";
import type { UserRole } from "@/contracts/auth";
import { hasRole } from "@/lib/auth";
import { useAuthStore } from "@/store/useAuthStore";

interface RequireRoleProps extends PropsWithChildren {
  allowedRoles: readonly UserRole[];
  fallback?: ReactNode;
}

export function RequireRole({
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

export default RequireRole;
