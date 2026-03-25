import { type ReactNode, type HTMLAttributes } from "react";

interface PanelProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
}

export default function Panel({ children, style, ...rest }: PanelProps) {
  return (
    <div
      {...rest}
      style={{
        background: "var(--bg-panel)",
        border: "1px solid var(--border-default)",
        borderRadius: "var(--radius-lg)",
        boxShadow: "var(--shadow-card)",
        padding: 16,
        ...style,
      }}
    >
      {children}
    </div>
  );
}
