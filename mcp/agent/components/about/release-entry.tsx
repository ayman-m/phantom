/**
 * Release-notes entry card — shared between the About modal, the
 * /about/whats-new page, and the /about/history page so all three
 * surfaces render the same shape.
 *
 * `highlight` adds the primary-container background that marks the
 * running version when the entry matches the currently-deployed
 * stack. Used as a visual anchor on the history page so operators
 * can tell where they sit in the timeline.
 */

import type { ReleaseNote } from "@/lib/release-notes";

export function ReleaseEntry({
  note,
  highlight,
}: {
  note: ReleaseNote;
  highlight?: boolean;
}) {
  return (
    <div
      className={`rounded-xl p-4 ${
        highlight
          ? "bg-primary-container/15 border border-primary/30"
          : "bg-white/3 border border-white/10"
      }`}
    >
      <div className="flex items-baseline gap-3 mb-2 flex-wrap">
        <span className="font-headline text-lg font-bold text-on-surface">
          v{note.version}
        </span>
        <span className="text-[11px] text-on-surface-variant font-mono">
          {note.date}
        </span>
        {note.security && (
          <span
            className="text-[10px] font-bold px-2 py-0.5 rounded-full flex items-center gap-1"
            style={{
              background: "rgba(147, 0, 10, 0.15)",
              border: "0.5px solid rgba(255, 180, 171, 0.3)",
              color: "#ffb4ab",
            }}
          >
            <span className="material-symbols-outlined text-[12px]">shield</span>
            Security
          </span>
        )}
        {note.breaking && (
          <span
            className="text-[10px] font-bold px-2 py-0.5 rounded-full"
            style={{
              background: "rgba(255, 180, 0, 0.15)",
              border: "0.5px solid rgba(255, 200, 100, 0.3)",
              color: "#ffc864",
            }}
          >
            Breaking
          </span>
        )}
        {highlight && (
          <span className="text-[10px] font-bold px-2 py-0.5 rounded-full text-primary border border-primary/30">
            Running
          </span>
        )}
      </div>
      <h3 className="text-sm font-bold text-on-surface mb-3">{note.title}</h3>
      <ul className="space-y-1.5 text-[13px] text-on-surface-variant leading-relaxed">
        {note.highlights.map((h, i) => (
          <li key={i} className="flex gap-2">
            <span className="text-primary/70 shrink-0">•</span>
            <span>{h}</span>
          </li>
        ))}
      </ul>
      {note.categories?.map((cat, i) => (
        <div key={i} className="mt-3 pt-3 border-t border-white/5">
          <p className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant mb-1.5">
            {cat.name}
          </p>
          <ul className="space-y-1 text-[12px] text-on-surface-variant leading-relaxed">
            {cat.items.map((item, j) => (
              <li key={j} className="flex gap-2">
                <span className="text-primary/70 shrink-0">·</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
