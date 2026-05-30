// Shared page header used at the top of each main tab (Resources, Generator,
// Review, …) — a small uppercase "eyebrow" (the phase/section) over a title.
// Extracted so every tab frames itself the same way; previously Generator had a
// local SectionHeader and Review inlined the identical markup.

export function PageHeader({ eyebrow, title }: { eyebrow: string; title: string }) {
  return (
    <div>
      <div className="text-[11px] tracking-wide uppercase text-ink-500">{eyebrow}</div>
      <h2 className="text-[18px] font-semibold text-ink-900 mt-0.5">{title}</h2>
    </div>
  );
}
