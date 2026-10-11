"use client";

/**
 * About Phantom — centered overlay modal showing version + runtime
 * metadata. Deliberately scoped to JUST the "what am I running"
 * question, modeled after the Cortex XSIAM About dialog.
 *
 * "What's new" and "Release history" intentionally live on separate
 * pages (/about/whats-new + /about/history) so they open in a new
 * browser tab — operators don't want long-form release notes inside
 * a modal they have to dismiss to keep working.
 *
 * Architecture: the running version comes from /api/agent/version
 * (compose-interpolated PHANTOM_VERSION). Static release-notes data
 * lives in lib/release-notes.ts so this works offline.
 *
 * Why we render via React Portal:
 *   The sidebar's <aside> has `backdrop-blur-xl` (backdrop-filter set).
 *   Per CSS spec, an ancestor with `backdrop-filter`, `transform`,
 *   `filter`, `perspective`, `will-change`, or `contain: paint`
 *   becomes the containing block for any `position: fixed`
 *   descendant — silently scoping the modal's `inset-0` to the
 *   sidebar's 16rem-wide rectangle instead of the viewport, so the
 *   modal would render as a panel inside the sidebar instead of as a
 *   centered overlay. Portaling the modal to
 *   document.body moves the DOM node out of the sidebar subtree, so
 *   `fixed` resolves against the viewport again.
 */

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { findRelease } from "@/lib/release-notes";

interface AboutModalProps {
  open: boolean;
  onClose: () => void;
}

const glassStyle = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

export function AboutModal({ open, onClose }: AboutModalProps) {
  const [version, setVersion] = useState<string | null>(null);
  // `mounted` gates the portal: document.body doesn't exist during
  // SSR, so we wait until after hydration to mount. Without this,
  // calling createPortal(..., document.body) would throw on the
  // server render. (Belt-and-suspenders — `open` is also false on
  // initial render, so the modal wouldn't try to render anyway —
  // but this protects future callers that might force-open.)
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    fetch("/api/agent/version", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled && data?.version) setVersion(String(data.version));
      })
      .catch(() => {
        // Network error → leave version null; modal shows "—".
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  // ESC closes the modal.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open || !mounted) return null;

  const inHistory = version ? Boolean(findRelease(version)) : false;

  // Portal target: document.body. This is the whole point of the
  // portal — escapes the sidebar's containing-block trap (see file
  // header). z-50 + the dark backdrop means we sit above page
  // content while still respecting the modal stacking convention.
  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4"
      style={{ background: "rgba(0, 0, 0, 0.6)" }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-md max-h-[85vh] flex flex-col rounded-2xl overflow-hidden"
        style={glassStyle}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <header className="px-6 py-5 flex items-start justify-between shrink-0">
          <p className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant">
            About
          </p>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-white/10 transition-colors text-on-surface-variant"
            aria-label="Close"
          >
            <span className="material-symbols-outlined text-xl">close</span>
          </button>
        </header>

        {/* Body — centered identity block + key facts */}
        <div className="flex-1 overflow-y-auto px-6 pb-6 space-y-6">
          <section className="text-center">
            <h2 className="font-headline text-3xl font-bold text-on-surface">
              Phantom
            </h2>
            <p className="font-mono text-base text-primary mt-1">
              v{version ?? "—"}
            </p>
            {!inHistory && version && (
              <p className="text-[11px] text-on-surface-variant mt-2">
                Dev build — release notes not yet committed for this version.
              </p>
            )}
          </section>

          <section>
            <p className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant mb-2">
              About this product
            </p>
            <p className="text-[13px] text-on-surface-variant leading-relaxed">
              Continuous SOC simulation platform: synthetic security log
              generation, scenario-based MITRE ATT&amp;CK telemetry, and
              AI-orchestrated red/blue workflows over MCP. Ships as a
              Docker Compose stack (phantom-agent, phantom-mcp,
              xlog, caldera).
            </p>
          </section>

          <section>
            <p className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant mb-2">
              Useful surfaces
            </p>
            <ul className="space-y-1.5 text-[13px] text-on-surface-variant leading-relaxed">
              <li className="flex gap-2">
                <span className="text-primary/70 shrink-0">•</span>
                <a className="text-primary hover:underline" href="/health">
                  /health
                </a>
                <span className="text-on-surface-variant/70">— stack health snapshot</span>
              </li>
              <li className="flex gap-2">
                <span className="text-primary/70 shrink-0">•</span>
                <a
                  className="text-primary hover:underline"
                  href="/observability/runtime-events"
                >
                  /observability/runtime-events
                </a>
                <span className="text-on-surface-variant/70">— event feed</span>
              </li>
              <li className="flex gap-2">
                <span className="text-primary/70 shrink-0">•</span>
                <a className="text-primary hover:underline" href="/connectors">
                  /connectors
                </a>
                <span className="text-on-surface-variant/70">— instances + probe</span>
              </li>
            </ul>
          </section>

          <section>
            <p className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant mb-2">
              Source
            </p>
            <a
              href="https://github.com/ayman-m/phantom"
              target="_blank"
              rel="noopener noreferrer"
              className="text-[13px] text-primary hover:underline inline-flex items-center gap-1"
            >
              github.com/ayman-m/phantom
              <span className="material-symbols-outlined text-[14px]">
                open_in_new
              </span>
            </a>
          </section>
        </div>
      </div>
    </div>,
    document.body,
  );
}
