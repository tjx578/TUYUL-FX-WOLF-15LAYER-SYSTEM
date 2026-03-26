// ============================================================
// TUYUL FX Wolf-15 — Institutional Button with Ripple Engine
// Production-ready reusable button with physics feedback.
// ============================================================
"use client";

import { useRef } from "react";
import clsx from "clsx";

interface ButtonProps {
  children: React.ReactNode;
  variant?: "primary" | "danger" | "ghost" | "take" | "skip";
  onClick?: (e: React.MouseEvent<HTMLButtonElement>) => void;
  disabled?: boolean;
  className?: string;
  style?: React.CSSProperties;
  type?: "button" | "submit" | "reset";
}

export default function Button({
  children,
  variant = "primary",
  onClick,
  disabled,
  className,
  style,
  type = "button",
}: ButtonProps) {
  const ref = useRef<HTMLButtonElement>(null);

  const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
    if (disabled) return;
    const button = ref.current;
    if (!button) return;

    // Ripple physics — use bounding rect for accuracy in nested layouts
    const rect = button.getBoundingClientRect();
    const diameter = Math.max(button.clientWidth, button.clientHeight);
    const radius = diameter / 2;

    const circle = document.createElement("span");
    circle.style.width = circle.style.height = `${diameter}px`;
    circle.style.left = `${e.clientX - rect.left - radius}px`;
    circle.style.top = `${e.clientY - rect.top - radius}px`;
    circle.classList.add("ripple");

    // Remove stale ripple
    const existing = button.getElementsByClassName("ripple")[0];
    if (existing) existing.remove();

    button.appendChild(circle);
    onClick?.(e);
  };

  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled}
      onClick={handleClick}
      style={style}
      className={clsx(
        // Base
        "relative overflow-hidden font-semibold transition-all duration-300",
        "flex items-center justify-content-center gap-1.5",
        // Variants
        variant === "primary" && [
          "btn btn-primary",
        ],
        variant === "danger" && [
          "btn",
          "bg-accent-red text-white",
        ],
        variant === "ghost" && [
          "btn btn-ghost",
        ],
        variant === "take" && [
          "btn btn-take",
        ],
        variant === "skip" && [
          "btn btn-skip",
        ],
        className
      )}
    >
      {children}
    </button>
  );
}
