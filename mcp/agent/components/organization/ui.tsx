"use client";

/**
 * Small presentational pieces shared by the /organization page: panels,
 * chips, labelled form fields, a modal, a copy button and loading/empty/error
 * states. Material 3 semantic tokens only; no logic about organizations here.
 */

import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { notify } from "@/lib/stores/notifications";
import { cn } from "@/lib/utils";

// ─── Buttons ─────────────────────────────────────────────────────────────────

type ButtonTone = "primary" | "neutral" | "danger";

const BUTTON_TONES: Record<ButtonTone, string> = {
  primary: "bg-primary/15 text-primary hover:bg-primary/20",
  neutral: "glass-panel text-on-surface-variant hover:text-on-surface",
  danger: "bg-error/10 text-error hover:bg-error/20",
};

export function Button({
  tone = "neutral",
  icon,
  children,
  onClick,
  disabled,
  type = "button",
  title,
  busy,
  className,
}: {
  tone?: ButtonTone;
  icon?: string;
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  type?: "button" | "submit";
  title?: string;
  busy?: boolean;
  className?: string;
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || busy}
      title={title}
      className={cn(
        "inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
        BUTTON_TONES[tone],
        className,
      )}
    >
      {busy ? (
        <span className="material-symbols-outlined text-base animate-spin" aria-hidden="true">
          sync
        </span>
      ) : icon ? (
        <span className="material-symbols-outlined text-base" aria-hidden="true">
          {icon}
        </span>
      ) : null}
      {children}
    </button>
  );
}

export function IconButton({
  icon,
  label,
  onClick,
  tone = "neutral",
  disabled,
}: {
  icon: string;
  label: string;
  onClick: () => void;
  tone?: "neutral" | "danger";
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className={cn(
        "p-1.5 rounded-md transition-colors disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
        tone === "danger"
          ? "text-on-surface-variant hover:text-error hover:bg-error/10"
          : "text-on-surface-variant hover:text-on-surface hover:bg-white/5",
      )}
    >
      <span className="material-symbols-outlined text-base" aria-hidden="true">
        {icon}
      </span>
    </button>
  );
}

// ─── Chips ───────────────────────────────────────────────────────────────────

export type ChipTone = "neutral" | "primary" | "success" | "warning" | "danger";

const CHIP_TONES: Record<ChipTone, string> = {
  neutral: "bg-surface-container-high text-on-surface-variant",
  primary: "bg-primary/15 text-primary",
  success: "bg-secondary/15 text-secondary",
  warning: "bg-tertiary/15 text-tertiary",
  danger: "bg-error/15 text-error",
};

export function Chip({ tone = "neutral", children, title }: { tone?: ChipTone; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider whitespace-nowrap",
        CHIP_TONES[tone],
      )}
    >
      {children}
    </span>
  );
}

// ─── Panels ──────────────────────────────────────────────────────────────────

export function Panel({
  title,
  icon,
  actions,
  children,
  className,
}: {
  title?: string;
  icon?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("glass-panel rounded-2xl p-5 space-y-4", className)}>
      {title ? (
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2.5">
            {icon ? (
              <span className="material-symbols-outlined text-lg text-primary" aria-hidden="true">
                {icon}
              </span>
            ) : null}
            <h2 className="text-sm font-headline font-bold text-on-surface uppercase tracking-wider">{title}</h2>
          </div>
          {actions}
        </div>
      ) : null}
      {children}
    </section>
  );
}

export function Banner({
  tone,
  icon,
  children,
}: {
  tone: "info" | "warning" | "error";
  icon: string;
  children: ReactNode;
}) {
  const styles = {
    info: "border-primary/30 bg-primary/10 text-on-surface",
    warning: "border-tertiary/30 bg-tertiary/10 text-on-surface",
    error: "border-error/30 bg-error/10 text-error",
  }[tone];
  const iconColor = { info: "text-primary", warning: "text-tertiary", error: "text-error" }[tone];
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cn("flex items-start gap-2.5 rounded-xl border px-4 py-3 text-xs leading-relaxed", styles)}
    >
      <span className={cn("material-symbols-outlined text-base shrink-0", iconColor)} aria-hidden="true">
        {icon}
      </span>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

/** A list of messages from the server, shown verbatim. */
export function ErrorList({ lines, title }: { lines: string[]; title?: string }) {
  if (lines.length === 0) return null;
  return (
    <div role="alert" className="rounded-xl border border-error/30 bg-error/10 px-4 py-3 text-xs text-error space-y-1.5">
      {title ? <div className="font-bold">{title}</div> : null}
      <ul className="list-disc pl-4 space-y-0.5 break-words">
        {lines.map((l, i) => (
          <li key={`${i}-${l}`}>{l}</li>
        ))}
      </ul>
    </div>
  );
}

export function WarningList({ lines, title }: { lines: string[]; title?: string }) {
  if (lines.length === 0) return null;
  return (
    <div className="rounded-xl border border-tertiary/30 bg-tertiary/10 px-4 py-3 text-xs text-on-surface space-y-1.5">
      {title ? (
        <div className="flex items-center gap-1.5 font-bold text-tertiary">
          <span className="material-symbols-outlined text-base" aria-hidden="true">
            warning
          </span>
          {title}
        </div>
      ) : null}
      <ul className="list-disc pl-4 space-y-0.5 text-on-surface-variant break-words">
        {lines.map((l, i) => (
          <li key={`${i}-${l}`}>{l}</li>
        ))}
      </ul>
    </div>
  );
}

export function EmptyState({ icon, title, children }: { icon: string; title: string; children?: ReactNode }) {
  return (
    <div className="rounded-2xl px-8 py-12 text-center space-y-2 glass-panel">
      <span className="material-symbols-outlined text-3xl text-on-surface-variant/50" aria-hidden="true">
        {icon}
      </span>
      <div className="text-base font-headline text-on-surface">{title}</div>
      {children ? <div className="text-sm text-on-surface-variant/80">{children}</div> : null}
    </div>
  );
}

export function SkeletonBlock({ className }: { className?: string }) {
  return <div className={cn("skeleton-shimmer rounded-lg", className)} aria-hidden="true" />;
}

/** Cold-load placeholder for the whole page body. */
export function PageSkeleton() {
  return (
    <div className="space-y-4" role="status" aria-label="Loading the organization">
      <SkeletonBlock className="h-24" />
      <SkeletonBlock className="h-10 w-2/3" />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <SkeletonBlock className="h-56" />
        <SkeletonBlock className="h-56" />
      </div>
      <SkeletonBlock className="h-72" />
    </div>
  );
}

export function LoadFailed({ lines, onRetry }: { lines: string[]; onRetry: () => void }) {
  return (
    <div className="space-y-3">
      <ErrorList lines={lines} title="Could not load the organization" />
      <Button tone="primary" icon="refresh" onClick={onRetry}>
        Retry
      </Button>
    </div>
  );
}

// ─── Form fields ─────────────────────────────────────────────────────────────

const CONTROL =
  "w-full px-3 py-1.5 text-xs rounded-lg bg-surface-container-low border border-outline-variant/30 outline-none focus:border-primary/50 text-on-surface placeholder:text-on-surface-variant/40 disabled:opacity-50 disabled:cursor-not-allowed";

export function TextField({
  label,
  value,
  onChange,
  placeholder,
  disabled,
  hint,
  mono,
  inputMode,
  autoFocus,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  disabled?: boolean;
  hint?: string;
  mono?: boolean;
  inputMode?: "numeric" | "text";
  autoFocus?: boolean;
}) {
  const id = useId();
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="text-xs font-label text-on-surface-variant/80">
        {label}
      </label>
      <input
        id={id}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        inputMode={inputMode}
        autoFocus={autoFocus}
        autoComplete="off"
        spellCheck={false}
        className={cn(CONTROL, mono && "font-mono")}
      />
      {hint ? <p className="text-[10px] text-on-surface-variant/50">{hint}</p> : null}
    </div>
  );
}

export interface SelectOption {
  value: string;
  label: string;
}

export function SelectField({
  label,
  value,
  onChange,
  options,
  disabled,
  hint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: SelectOption[];
  disabled?: boolean;
  hint?: string;
}) {
  const id = useId();
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="text-xs font-label text-on-surface-variant/80">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className={CONTROL}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {hint ? <p className="text-[10px] text-on-surface-variant/50">{hint}</p> : null}
    </div>
  );
}

export function CheckField({
  label,
  checked,
  onChange,
  hint,
  disabled,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  hint?: string;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex items-start gap-2">
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        disabled={disabled}
        className="mt-0.5 h-4 w-4 accent-primary"
      />
      <label htmlFor={id} className="text-xs text-on-surface">
        {label}
        {hint ? <span className="block text-[10px] text-on-surface-variant/60">{hint}</span> : null}
      </label>
    </div>
  );
}

/** Search box with a leading icon. */
export function SearchField({
  value,
  onChange,
  placeholder,
  label,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  label: string;
}) {
  const id = useId();
  return (
    <div className="flex-1 min-w-[200px] flex items-center gap-2 px-3 rounded-lg bg-surface-container-low border border-outline-variant/30 focus-within:border-primary/50">
      <span className="material-symbols-outlined text-base text-on-surface-variant/60" aria-hidden="true">
        search
      </span>
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <input
        id={id}
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="flex-1 bg-transparent border-0 outline-0 py-1.5 text-xs text-on-surface placeholder:text-on-surface-variant/40"
      />
    </div>
  );
}

/** Compact filter select used above tables. */
export function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: SelectOption[];
}) {
  const id = useId();
  return (
    <div className="flex items-center gap-2">
      <label htmlFor={id} className="text-[10px] uppercase tracking-wider text-on-surface-variant/60">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="px-2.5 py-1.5 text-xs rounded-lg bg-surface-container-low border border-outline-variant/30 outline-none focus:border-primary/50 text-on-surface"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

// ─── Modal ───────────────────────────────────────────────────────────────────

/**
 * Centered dialog. Escape or a click on the backdrop closes it; focus moves
 * into the dialog on open and returns to the opener on close. A `confirmAction`
 * opened on top handles its own Escape in the capture phase, so it never
 * closes this dialog by accident.
 */
export function Modal({
  title,
  icon,
  onClose,
  children,
  footer,
  wide,
}: {
  title: string;
  icon?: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const first = panelRef.current?.querySelector<HTMLElement>("input, select, textarea, button:not([data-modal-close])");
    first?.focus();
    return () => opener?.focus?.();
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-[2px] p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.stopPropagation();
            onClose();
          }
        }}
        className={cn(
          "w-full max-h-[90vh] flex flex-col rounded-2xl bg-surface-container border border-outline-variant/30 shadow-2xl",
          wide ? "max-w-3xl" : "max-w-lg",
        )}
      >
        <div className="flex items-center justify-between gap-3 px-6 pt-5 pb-3">
          <div className="flex items-center gap-2.5 min-w-0">
            {icon ? (
              <span className="material-symbols-outlined text-xl text-primary" aria-hidden="true">
                {icon}
              </span>
            ) : null}
            <h2 id={titleId} className="font-headline text-base font-bold text-on-surface truncate">
              {title}
            </h2>
          </div>
          <button
            type="button"
            data-modal-close
            onClick={onClose}
            aria-label="Close"
            className="p-1.5 rounded-md text-on-surface-variant hover:text-on-surface hover:bg-white/5"
          >
            <span className="material-symbols-outlined text-lg" aria-hidden="true">
              close
            </span>
          </button>
        </div>
        <div className="px-6 pb-4 overflow-y-auto custom-scrollbar space-y-4">{children}</div>
        {footer ? <div className="flex justify-end gap-2 px-6 py-4 border-t border-outline-variant/20">{footer}</div> : null}
      </div>
    </div>
  );
}

// ─── Clipboard ───────────────────────────────────────────────────────────────

export function CopyButton({ text, label }: { text: string; label: string }) {
  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      notify("success", "Copied", text.length > 80 ? `${text.slice(0, 77)}…` : text);
    } catch {
      notify("error", "Could not copy", "The browser blocked clipboard access. Select the text and copy it by hand.");
    }
  }, [text]);
  return <IconButton icon="content_copy" label={label} onClick={() => void copy()} />;
}

// ─── Hooks ───────────────────────────────────────────────────────────────────

/** `value`, delayed until it has been stable for `ms`. */
export function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

// ─── Tables ──────────────────────────────────────────────────────────────────

export function TableShell({ children, caption }: { children: ReactNode; caption: string }) {
  return (
    <div className="overflow-x-auto custom-scrollbar rounded-xl border border-outline-variant/20">
      <table className="w-full text-xs text-left">
        <caption className="sr-only">{caption}</caption>
        {children}
      </table>
    </div>
  );
}

export function Th({ children, className }: { children?: ReactNode; className?: string }) {
  return (
    <th
      scope="col"
      className={cn(
        "px-3 py-2 text-[10px] font-label uppercase tracking-wider text-on-surface-variant/70 whitespace-nowrap bg-surface-container-low/60",
        className,
      )}
    >
      {children}
    </th>
  );
}

export function Td({ children, className, mono }: { children?: ReactNode; className?: string; mono?: boolean }) {
  return (
    <td className={cn("px-3 py-2 align-middle text-on-surface", mono && "font-mono text-[11px]", className)}>
      {children}
    </td>
  );
}

export const ROW_CLASS = "border-t border-outline-variant/20 hover:bg-surface-container/60 transition-colors";

export function TruncatedNote({ shown, total }: { shown: number; total: number }) {
  return (
    <p className="text-[11px] text-tertiary">
      Only the first {shown} of {total} rows are loaded.
    </p>
  );
}

/** What the server did for an edit (e.g. the host, login and manager it filled in), verbatim. */
export function NotesBanner({ notes, onDismiss }: { notes: string[]; onDismiss: () => void }) {
  if (notes.length === 0) return null;
  return (
    <div role="status" className="flex items-start gap-2.5 rounded-xl border border-secondary/30 bg-secondary/10 px-4 py-3 text-xs">
      <span className="material-symbols-outlined text-base text-secondary shrink-0" aria-hidden="true">
        check_circle
      </span>
      <ul className="flex-1 min-w-0 space-y-0.5 text-on-surface break-words">
        {notes.map((n, i) => (
          <li key={`${i}-${n}`}>{n}</li>
        ))}
      </ul>
      <IconButton icon="close" label="Dismiss" onClick={onDismiss} />
    </div>
  );
}
