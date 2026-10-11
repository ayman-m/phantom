"use client";

/**
 * Sidebar "About" entry — looks like a normal nav row (icon + label
 * when expanded, icon-only when collapsed) but clicking opens a
 * popover floating to the RIGHT of the sidebar with three actions:
 *
 *   * About               — opens AboutModal (centered overlay) with
 *                            version + product blurb
 *   * What's new          — opens /about/whats-new in a NEW BROWSER TAB
 *                            (long-form release notes for the running
 *                            version; operators don't want to dismiss
 *                            a modal to keep working)
 *   * Release history     — opens /about/history in a NEW BROWSER TAB
 *                            (full timeline)
 *
 * Visually mirrors `FooterLink` for the trigger so it blends with
 * Notifications + the user profile. The popover is the same
 * pattern Cortex XSIAM uses for its operator dropdown (small
 * floating menu anchored to the trigger).
 */

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { AboutModal } from "./about-modal";

interface VersionMenuProps {
  collapsed: boolean;
}

export function VersionMenu({ collapsed }: VersionMenuProps) {
  const [open, setOpen] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  // Click-outside dismisses the popover (pointerdown so it fires
  // before any subsequent click registers — avoids double-fire when
  // going from one popover to another).
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      const t = e.target as Node;
      if (
        triggerRef.current?.contains(t) ||
        popoverRef.current?.contains(t)
      ) {
        return;
      }
      setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  // ESC dismisses the popover.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const handleAbout = () => {
    setOpen(false);
    setModalOpen(true);
  };

  const openInNewTab = (path: string) => {
    setOpen(false);
    window.open(path, "_blank", "noopener,noreferrer");
  };

  return (
    <>
      <div className="relative">
        <button
          ref={triggerRef}
          type="button"
          onClick={() => setOpen((v) => !v)}
          className={cn(
            // Mirror FooterLink's shape so the row blends with
            // Notifications + the profile entry above it.
            "flex items-center gap-3 rounded-lg transition-all duration-300 w-full",
            collapsed ? "px-0 py-2.5 justify-center" : "px-3 py-2.5",
            open
              ? "bg-secondary-container/25 text-secondary"
              : "sidebar-text sidebar-hover",
          )}
          title={collapsed ? "About Phantom" : undefined}
          aria-label="About Phantom"
          aria-expanded={open}
          aria-haspopup="menu"
        >
          <span className="material-symbols-outlined text-lg flex-shrink-0">
            info
          </span>
          {!collapsed && <span className="text-sm font-medium">About</span>}
        </button>

        {open && (
          <div
            ref={popoverRef}
            role="menu"
            // Anchored above the trigger and offset right so it
            // doesn't cover the trigger row. min-w gives the items
            // room to read; z-50 sits above main content + the
            // sidebar's own internal layers.
            //
            // Background + border MUST be CSS-var tokens so the
            // popover swaps with the [data-theme="light"] flip. A
            // hardcoded dark rgba (the original) collided with light
            // theme's dark text colors → dark-on-dark, unreadable.
            // m3-surface-container-highest is the highest-elevation
            // neutral surface in both themes (≈#343340 dark, ≈#cce0ed
            // light); m3-outline-variant is the matching soft border.
            className="absolute z-50 left-full ml-3 bottom-0 min-w-[240px] rounded-xl py-1 shadow-2xl"
            style={{
              background: "var(--m3-surface-container-highest)",
              border: "1px solid var(--m3-outline-variant)",
              backdropFilter: "none",
            }}
          >
            <MenuItem
              icon="info"
              label="About"
              hint="Version + product details"
              onClick={handleAbout}
            />
            <MenuItem
              icon="auto_awesome"
              label="What's new"
              hint="Highlights of the running release"
              external
              onClick={() => openInNewTab("/about/whats-new")}
            />
            {/* Divider uses on-surface (theme-aware text color) at low
                opacity so it stays subtle in both themes. The original
                border-white/5 vanished entirely against light theme's
                near-white surface. */}
            <div className="my-1 border-t border-on-surface/10" />
            <MenuItem
              icon="history"
              label="Release history"
              hint="All versions, newest first"
              external
              onClick={() => openInNewTab("/about/history")}
            />
          </div>
        )}
      </div>

      <AboutModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </>
  );
}

function MenuItem({
  icon,
  label,
  hint,
  external,
  onClick,
}: {
  icon: string;
  label: string;
  hint?: string;
  external?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      // hover bg uses on-surface (theme-aware text color) at low
      // opacity so it dims correctly in BOTH themes. The original
      // hover:bg-white/5 was invisible against light theme's
      // near-white surface.
      className="w-full flex items-start gap-2.5 px-3 py-2 text-left text-on-surface hover:bg-on-surface/8 transition-colors"
    >
      <span className="material-symbols-outlined text-[16px] text-on-surface-variant mt-0.5 shrink-0">
        {icon}
      </span>
      <div className="flex-1 min-w-0">
        <p className="text-[13px] font-medium leading-tight flex items-center gap-1.5">
          {label}
          {external && (
            <span className="material-symbols-outlined text-[12px] text-on-surface-variant/60">
              open_in_new
            </span>
          )}
        </p>
        {hint && (
          <p className="text-[10px] text-on-surface-variant/70 leading-tight mt-0.5">
            {hint}
          </p>
        )}
      </div>
    </button>
  );
}
