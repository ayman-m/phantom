"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import { useConfirmStore } from "@/lib/stores/confirm";

/**
 * Modal host for `confirmAction()` (lib/stores/confirm.ts). Mounted once in
 * components/providers.tsx. Escape (handled in the capture phase, so no other
 * Escape handler also acts on it) or a click on the backdrop dismisses
 * (resolves false); Tab cycles between the two buttons while the dialog is
 * open; focus returns to the element that opened it.
 */
export function ConfirmDialogHost() {
  const head = useConfirmStore((s) => s.queue[0]);
  const settle = useConfirmStore((s) => s.settle);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const activeId = head?.id;
  const tone = head?.options.tone ?? "default";

  useEffect(() => {
    if (activeId === undefined) return;
    openerRef.current = document.activeElement as HTMLElement | null;
    // A destructive prompt starts on Cancel so a stray Enter cannot delete.
    (tone === "danger" ? cancelRef : confirmRef).current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        // Capture phase + stop: a page-level Escape handler (a slide-over
        // closing itself) must not also act on the key that dismisses this.
        e.preventDefault();
        e.stopPropagation();
        settle(false);
        return;
      }
      if (e.key === "Tab") {
        const a = cancelRef.current;
        const b = confirmRef.current;
        if (!a || !b) return;
        if (e.shiftKey && document.activeElement === a) {
          e.preventDefault();
          b.focus();
        } else if (!e.shiftKey && document.activeElement === b) {
          e.preventDefault();
          a.focus();
        }
      }
    }
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      openerRef.current?.focus?.();
    };
  }, [activeId, tone, settle]);

  if (!head) return null;
  const { title, message, confirmLabel, cancelLabel } = head.options;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 backdrop-blur-[2px] p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) settle(false);
      }}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby={message ? "confirm-dialog-message" : undefined}
        className="w-full max-w-md rounded-2xl p-6 shadow-2xl space-y-4"
        style={{
          background: "var(--m3-surface-container)",
          border: "0.5px solid var(--glass-border)",
        }}
      >
        <div className="flex items-start gap-3">
          <span
            className={cn(
              "material-symbols-outlined text-2xl shrink-0",
              tone === "danger" ? "text-error" : "text-primary",
            )}
            aria-hidden="true"
          >
            {tone === "danger" ? "warning" : "help"}
          </span>
          <div className="min-w-0 space-y-1.5">
            <h2
              id="confirm-dialog-title"
              className="font-headline text-base font-bold text-on-surface"
            >
              {title}
            </h2>
            {message && (
              <p
                id="confirm-dialog-message"
                className="text-sm text-on-surface-variant leading-relaxed break-words"
              >
                {message}
              </p>
            )}
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <button
            ref={cancelRef}
            type="button"
            onClick={() => settle(false)}
            className="px-4 py-2 rounded-xl text-xs font-medium text-on-surface-variant hover:bg-white/5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            {cancelLabel ?? "Cancel"}
          </button>
          <button
            ref={confirmRef}
            type="button"
            onClick={() => settle(true)}
            className={cn(
              "px-4 py-2 rounded-xl text-xs font-bold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
              tone === "danger"
                ? "bg-error text-on-error hover:opacity-90"
                : "btn-gradient text-white hover:opacity-90",
            )}
          >
            {confirmLabel ?? "Confirm"}
          </button>
        </div>
      </div>
    </div>
  );
}
