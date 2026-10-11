"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";

export interface ThinkingSectionProps {
  reasoning?: string | readonly string[] | null;
  className?: string;
}

export function ThinkingSection({
  reasoning,
  className,
}: ThinkingSectionProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const text = typeof reasoning === "string" ? reasoning : (reasoning ?? []).join("");

  if (!text.trim()) {
    return null;
  }

  return (
    <div
      className={cn(
        "bg-surface-container-low rounded-xl border border-white/5 overflow-hidden",
        className,
      )}
    >
      <button
        type="button"
        aria-expanded={isExpanded}
        onClick={() => setIsExpanded((current) => !current)}
        className="flex items-center gap-2 w-full p-3 text-[10px] font-headline uppercase tracking-widest text-primary/70 cursor-pointer hover:bg-white/5 transition-colors"
      >
        <span
          className={cn(
            "material-symbols-outlined text-sm transition-transform",
            isExpanded && "rotate-180",
          )}
          aria-hidden="true"
        >
          expand_more
        </span>
        Thinking...
      </button>

      {isExpanded && (
        <div className="p-4 pt-0 text-[11px] font-mono text-on-surface-variant leading-relaxed whitespace-pre-wrap">
          {text}
        </div>
      )}
    </div>
  );
}
