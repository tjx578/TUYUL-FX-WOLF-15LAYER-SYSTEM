"use client";
import { useEffect, useState } from "react";

/**
 * Renders children only on the client side (after hydration).
 * Prevents SSR/CSR mismatch for components that read browser-only state.
 */
export default function ClientOnly({
  children,
  fallback = null,
}: {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return mounted ? <>{children}</> : <>{fallback}</>;
}
