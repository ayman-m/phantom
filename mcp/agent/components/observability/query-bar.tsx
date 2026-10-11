"use client";

/**
 * Shared Lucene-light query bar for /observability/* pages.
 *
 * Same parser (lib/observability-query.ts) drives /events, /logs, and
 * /traces — operators learn the syntax once and it works everywhere.
 *
 * Autocomplete: when the input is focused, a dropdown shows
 * token-aware suggestions (filter keys, known action enums, actor
 * shortcuts, dynamic job names). ↑/↓ navigates, Enter or Tab accepts,
 * Esc dismisses. Click also accepts. Suggestions are scoped to the
 * LAST whitespace-delimited token so multi-clause queries complete
 * one clause at a time without disturbing the rest. See
 * lib/observability-suggestions.ts for the suggestion logic.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { type ParsedQuery } from "@/lib/observability-query";
import {
  applySuggestion,
  getSuggestions,
  type DynamicSources,
  type Suggestion,
} from "@/lib/observability-suggestions";

export interface QueryBarProps {
  value: string;
  onChange: (next: string) => void;
  onSubmit: () => void;
  onClear: () => void;
  parsed: ParsedQuery | null;
  placeholder?: string;
  /** Dynamic suggestion sources (e.g. job names from /api/agent/jobs).
   *  Pages fetch and pass these in; the QueryBar is presentation. */
  dynamicSources?: DynamicSources;
}

const glassStyle = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

export function QueryBar({
  value,
  onChange,
  onSubmit,
  onClear,
  parsed,
  placeholder,
  dynamicSources,
}: QueryBarProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [cursor, setCursor] = useState(0);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [highlightedIdx, setHighlightedIdx] = useState(0);

  // Compute the flat list of suggestions for the current buffer +
  // cursor, plus their group memberships. Groups exist for visual
  // labeling only; keyboard nav indexes into the flat list.
  const groups = useMemo(
    () => getSuggestions(value, cursor, dynamicSources),
    [value, cursor, dynamicSources],
  );
  const flatItems: Suggestion[] = useMemo(
    () => groups.flatMap((g) => g.items),
    [groups],
  );

  // Reset highlight when the suggestion set changes (typing narrows
  // the list; we don't want stale indices pointing past the end).
  useEffect(() => {
    if (highlightedIdx >= flatItems.length) {
      setHighlightedIdx(0);
    }
  }, [flatItems.length, highlightedIdx]);

  const acceptSuggestion = useCallback(
    (s: Suggestion) => {
      const { next, cursor: newCursor } = applySuggestion(value, cursor, s);
      onChange(next);
      // Update cursor on the input element after React rerenders.
      // Wrap in queueMicrotask so the value-change has been applied;
      // setSelectionRange before that point uses the OLD value length.
      queueMicrotask(() => {
        const el = inputRef.current;
        if (el) {
          el.focus();
          el.setSelectionRange(newCursor, newCursor);
          setCursor(newCursor);
        }
      });
      // Keep the dropdown open — the operator may want to see the
      // next layer (e.g. after picking `target:job:` they'll see
      // matching job names). Closes on Escape or blur.
    },
    [value, cursor, onChange],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (showSuggestions && flatItems.length > 0) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setHighlightedIdx((i) => (i + 1) % flatItems.length);
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          setHighlightedIdx(
            (i) => (i - 1 + flatItems.length) % flatItems.length,
          );
          return;
        }
        if (e.key === "Tab") {
          e.preventDefault();
          acceptSuggestion(flatItems[highlightedIdx]);
          return;
        }
        if (e.key === "Enter") {
          // If the operator is highlighting a non-default suggestion
          // (i.e. they navigated with arrow keys), Enter accepts it.
          // Otherwise Enter submits the query — that matches GitHub /
          // VS Code search behavior where Enter without nav = submit.
          if (highlightedIdx > 0) {
            e.preventDefault();
            acceptSuggestion(flatItems[highlightedIdx]);
            return;
          }
          // First-position highlight: treat as submit, not accept.
          // The operator can still Tab to accept the first suggestion
          // explicitly; Enter is reserved for "I'm done typing, run."
        }
        if (e.key === "Escape") {
          setShowSuggestions(false);
          return;
        }
      }
      if (e.key === "Enter") {
        // Default enter → submit.
        e.preventDefault();
        setShowSuggestions(false);
        onSubmit();
      }
    },
    [showSuggestions, flatItems, highlightedIdx, acceptSuggestion, onSubmit],
  );

  // Track cursor position on every input/select event so the
  // suggestion engine sees the same cursor the browser does.
  const handleInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onChange(e.target.value);
      setCursor(e.target.selectionStart ?? e.target.value.length);
      setShowSuggestions(true);
      setHighlightedIdx(0);
    },
    [onChange],
  );

  const handleSelect = useCallback(
    (e: React.SyntheticEvent<HTMLInputElement>) => {
      const el = e.currentTarget;
      setCursor(el.selectionStart ?? el.value.length);
    },
    [],
  );

  const hasActiveFilters =
    parsed != null &&
    (parsed.action ||
      parsed.actor ||
      parsed.target ||
      parsed.target_prefix ||
      parsed.trigger ||
      parsed.trigger_prefix ||
      parsed.since ||
      parsed.until);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        setShowSuggestions(false);
        onSubmit();
      }}
      // Form gets `z-50` (and explicit position:relative via the
      // class) so its stacking context paints above the sibling
      // table below. Without this, the table — which has its own
      // `backdrop-filter: blur(...)` glass style and therefore its
      // own stacking context — paints over the autocomplete
      // dropdown because it comes later in DOM order. The dropdown
      // inside this form can stay at its current z-index; what
      // matters is that THIS form sits above the table.
      className="rounded-xl p-4 space-y-3 relative z-50"
      style={glassStyle}
    >
      <div className="flex items-center gap-2">
        <span className="material-symbols-outlined text-on-surface-variant/60 text-lg">
          search
        </span>
        <input
          ref={inputRef}
          value={value}
          onChange={handleInput}
          onSelect={handleSelect}
          onKeyDown={handleKeyDown}
          onFocus={() => setShowSuggestions(true)}
          // Defer the close so a click on a suggestion item registers
          // before the dropdown unmounts. 200ms is the same delay
          // GitHub's command palette uses for the same reason.
          onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
          placeholder={
            placeholder ??
            "action:tool_call target:job:my-job*  since:2026-05-02"
          }
          className="flex-1 bg-transparent border-none rounded-lg px-1 py-1.5 text-sm font-mono text-on-surface focus:ring-0 outline-none placeholder:text-on-surface-variant/30"
          spellCheck={false}
          autoComplete="off"
          aria-autocomplete="list"
          aria-expanded={showSuggestions && flatItems.length > 0}
        />
        {value && (
          <button
            type="button"
            onClick={onClear}
            className="text-on-surface-variant/60 hover:text-on-surface text-[10px] uppercase tracking-widest font-bold"
          >
            clear
          </button>
        )}
        <button
          type="submit"
          className="px-3 py-1.5 rounded-lg text-[10px] uppercase tracking-widest font-bold bg-primary/15 text-primary border border-primary/30 hover:bg-primary/25"
        >
          Apply
        </button>
      </div>

      {/* Autocomplete dropdown — anchored below the input row, slides
          out of view when there are no matches or focus is gone. */}
      {showSuggestions && flatItems.length > 0 && (
        <div
          className="absolute left-4 right-4 top-[60px] z-30 max-h-80 overflow-y-auto rounded-lg shadow-2xl"
          style={glassStyle}
          role="listbox"
        >
          {groups.map((group, gi) => {
            // Compute the global flat index of each item so keyboard
            // highlights work across group boundaries.
            const offset = groups
              .slice(0, gi)
              .reduce((sum, g) => sum + g.items.length, 0);
            return (
              <div key={group.label} className="py-1.5">
                <div className="px-3 py-1 text-[9px] uppercase tracking-widest text-on-surface-variant/50 font-bold">
                  {group.label}
                </div>
                {group.items.map((item, ii) => {
                  const idx = offset + ii;
                  const isHighlighted = idx === highlightedIdx;
                  return (
                    <button
                      key={`${group.label}-${ii}`}
                      type="button"
                      role="option"
                      aria-selected={isHighlighted}
                      onMouseEnter={() => setHighlightedIdx(idx)}
                      onMouseDown={(e) => {
                        // Use mousedown not click so the input's blur
                        // handler doesn't fire first and close the
                        // dropdown before our handler runs.
                        e.preventDefault();
                        acceptSuggestion(item);
                      }}
                      className={`w-full text-left px-3 py-1.5 text-xs font-mono flex items-center justify-between gap-2 transition-colors ${
                        isHighlighted
                          ? "bg-primary/15 text-primary"
                          : "text-on-surface hover:bg-white/5"
                      }`}
                    >
                      <span className="truncate">{item.label}</span>
                      {item.hint && (
                        <span
                          className={`text-[10px] truncate ${
                            isHighlighted
                              ? "text-primary/60"
                              : "text-on-surface-variant/50"
                          }`}
                        >
                          {item.hint}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            );
          })}
          <div className="px-3 py-1.5 text-[10px] text-on-surface-variant/40 border-t border-white/5">
            <kbd className="px-1 py-0.5 rounded bg-white/5 font-mono">↑↓</kbd>{" "}
            navigate ·{" "}
            <kbd className="px-1 py-0.5 rounded bg-white/5 font-mono">Tab</kbd>{" "}
            accept ·{" "}
            <kbd className="px-1 py-0.5 rounded bg-white/5 font-mono">Enter</kbd>{" "}
            run · <kbd className="px-1 py-0.5 rounded bg-white/5 font-mono">Esc</kbd>{" "}
            close
          </div>
        </div>
      )}

      {hasActiveFilters && parsed && (
        <div className="flex flex-wrap gap-1.5 pl-7">
          {parsed.action && <FilterChip label="action" value={parsed.action} />}
          {parsed.actor && <FilterChip label="actor" value={parsed.actor} />}
          {parsed.target && <FilterChip label="target" value={parsed.target} />}
          {parsed.target_prefix && (
            <FilterChip label="target" value={`${parsed.target_prefix}*`} />
          )}
          {parsed.trigger && (
            <FilterChip label="trigger" value={parsed.trigger} />
          )}
          {parsed.trigger_prefix && (
            <FilterChip label="trigger" value={`${parsed.trigger_prefix}*`} />
          )}
          {parsed.since && <FilterChip label="since" value={parsed.since} />}
          {parsed.until && <FilterChip label="until" value={parsed.until} />}
        </div>
      )}

      {parsed && parsed.parseErrors.length > 0 && (
        <div className="pl-7 space-y-0.5">
          {parsed.parseErrors.map((err, i) => (
            <div key={i} className="text-[11px] text-yellow-400/80">
              <span className="material-symbols-outlined text-[12px] align-middle mr-1">
                warning
              </span>
              {err}
            </div>
          ))}
        </div>
      )}

      {!value && !showSuggestions && (
        <div className="pl-7 text-[11px] text-on-surface-variant/50 leading-relaxed">
          Lucene-light syntax · <code className="font-mono">key:value</code>{" "}
          · <code className="font-mono">key:prefix*</code> · supported keys:{" "}
          <code className="font-mono">action</code>{" "}
          <code className="font-mono">actor</code>{" "}
          <code className="font-mono">target</code>{" "}
          <code className="font-mono">trigger</code>{" "}
          <code className="font-mono">since</code>{" "}
          <code className="font-mono">until</code>
          <span className="text-on-surface-variant/40">
            {" "}
            · click the bar for autocomplete
          </span>
        </div>
      )}
    </form>
  );
}

function FilterChip({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-primary/10 border border-primary/30 text-[10px] font-mono">
      <span className="text-primary/70 uppercase tracking-wider">{label}</span>
      <span className="text-on-surface">{value}</span>
    </span>
  );
}
