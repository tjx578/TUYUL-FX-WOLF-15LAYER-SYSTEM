interface PanelWrapperProps {
  title: string;
  children: React.ReactNode;
}

export function PanelWrapper({ title, children }: PanelWrapperProps) {
  return (
    <section className="rounded-2xl border border-white/10 bg-slate-900/70 p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-300">{title}</h2>
      {children}
    </section>
  );
}
