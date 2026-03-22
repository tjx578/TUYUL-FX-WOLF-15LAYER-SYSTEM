import React from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import fs from "fs";
import path from "path";

// ── next/navigation mock ────────────────────────────────────────────────────
vi.mock("next/navigation", () => ({
  usePathname: () => "/trades",
}));

// ── framer-motion mock ──────────────────────────────────────────────────────
// Render the structural primitives as plain divs so jsdom doesn't choke on
// Web Animations API features that Framer Motion requires at runtime.
// `layout` is explicitly extracted and discarded to make clear that it is
// intentionally not forwarded — this mirrors the fix in RouteTransition.tsx.
function MotionDiv({
  children,
  layout: _layout,
  ...rest
}: React.HTMLAttributes<HTMLDivElement> & { layout?: boolean }) {
  return <div {...rest}>{children}</div>;
}
MotionDiv.displayName = "MotionDiv";

vi.mock("framer-motion", () => ({
  AnimatePresence: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
  motion: {
    div: MotionDiv,
  },
}));

// ── Subject under test ──────────────────────────────────────────────────────
import RouteTransition from "@/components/layout/RouteTransition";

// ── Source file path (for static regression check) ──────────────────────────
const ROUTE_TRANSITION_SRC = path.resolve(
  __dirname,
  "../components/layout/RouteTransition.tsx"
);

describe("RouteTransition", () => {
  it("renders children", () => {
    render(
      <RouteTransition>
        <p data-testid="child">Hello</p>
      </RouteTransition>
    );

    expect(screen.getByTestId("child")).toBeTruthy();
  });

  it("does not use the layout prop on motion.div (regression: fiber crash fix)", () => {
    // Static source check: the `layout` prop must not appear on the motion.div.
    // This guards against re-introducing the prop that caused the React
    // concurrent/fiber null-assertion crash (n || rD(e, !0)) on navigation.
    const source = fs.readFileSync(ROUTE_TRANSITION_SRC, "utf-8");

    // Strip all comment forms so documentation that mentions 'layout' doesn't
    // produce false negatives. Block comments first, then line comments.
    const withoutComments = source
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/\/\/[^\n]*/g, "");

    // After stripping all comments, 'layout' must not appear anywhere —
    // it has no legitimate use in the component code outside of comments.
    expect(withoutComments).not.toContain("layout");
  });
});
