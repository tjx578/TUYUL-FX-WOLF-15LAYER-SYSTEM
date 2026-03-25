"use client";

interface ButtonProps {
  children: React.ReactNode;
  variant?: "primary" | "danger" | "ghost";
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
  style,
  type = "button",
}: ButtonProps) {
  const variantStyles: React.CSSProperties =
    variant === "primary"
      ? { background: "var(--accent)", color: "#fff", border: "1px solid var(--accent-dim)" }
      : variant === "danger"
      ? { background: "var(--red-glow)", color: "var(--red)", border: "1px solid var(--border-danger)" }
      : {
          background: "transparent",
          color: "var(--text-secondary)",
          border: "1px solid var(--border-default)",
        };

  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 6,
        padding: "6px 14px",
        borderRadius: "var(--radius-sm)",
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: "0.06em",
        textTransform: "uppercase",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.4 : 1,
        transition: "all 0.15s ease",
        whiteSpace: "nowrap",
        ...variantStyles,
        ...style,
      }}
    >
      {children}
    </button>
  );
}
