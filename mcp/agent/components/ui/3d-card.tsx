"use client";

/**
 * Card primitives. Pre-cleanup these had a 3D-tilt animated variant
 * gated by `isAnimatedUiEnabled`; that flag was removed when the
 * animated UI chrome went away (no clean A2UI mapping). The exports
 * stay so existing consumers (app/skills/page.tsx) keep working
 * without a refactor — they just render flat cards now.
 */

import React from "react";

import { cn } from "@/lib/utils";

export const CardContainer = ({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) => <div className={cn("group", className)}>{children}</div>;

export const CardBody = ({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) => (
  <div
    className={cn(
      "relative h-full w-full rounded-3xl border border-slate-200/80 bg-white/80 p-6 shadow-sm",
      className,
    )}
  >
    {children}
  </div>
);

export const CardItem = ({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
  translateZ?: number;  // accepted but ignored — kept for caller compat
}) => <div className={cn(className)}>{children}</div>;
