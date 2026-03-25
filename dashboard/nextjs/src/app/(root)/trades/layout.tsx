/**
 * @deprecated CUTOVER-PHASE-9
 * Metadata ownership moved to (control)/trades/layout.tsx.
 * This layout is retained only because (root)/trades/signals/page.tsx
 * (a redirect stub) still nests under it.
 * DELETE this entire directory once trades/signals redirect is removed.
 */
import type { PropsWithChildren } from "react";

export default function DeprecatedTradeDeskLayout({ children }: PropsWithChildren) {
  return <>{children}</>;
}
