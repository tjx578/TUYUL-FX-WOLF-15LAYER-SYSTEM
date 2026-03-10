import clsx from "clsx";

interface CardProps {
  className?: string;
  children: React.ReactNode;
}

export function Card({ className, children }: CardProps) {
  return (
    <section className={clsx("rounded-2xl border border-white/10 bg-slate-900/70 p-4", className)}>
      {children}
    </section>
  );
}
