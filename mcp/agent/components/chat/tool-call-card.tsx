"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import type { ToolCall } from "@/lib/stores/chat";

export interface ToolCallCardProps {
  toolCall: ToolCall;
  className?: string;
}

function getStatusIcon(status: ToolCall["status"]) {
  switch (status) {
    case "pending":
      return { icon: "hourglass_empty", className: "text-primary animate-spin", ariaLabel: "Tool call pending" };
    case "success":
      return { icon: "check_circle", className: "text-secondary", ariaLabel: "Tool call succeeded" };
    case "error":
      return { icon: "error", className: "text-error", ariaLabel: "Tool call failed" };
  }
}

function formatArguments(args: Record<string, unknown>): string {
  return JSON.stringify(args, null, 2);
}

export function ToolCallCard({ toolCall, className }: ToolCallCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const hasArguments = Object.keys(toolCall.arguments).length > 0;
  const statusIcon = getStatusIcon(toolCall.status);

  return (
    <div className={cn("glass-panel rounded-xl overflow-hidden", className)}>
      <button
        type="button"
        aria-expanded={isExpanded}
        onClick={() => setIsExpanded((current) => !current)}
        className="w-full p-3 flex items-center justify-between hover:bg-white/5 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span
            className={cn("material-symbols-outlined", statusIcon.className)}
            style={{ fontVariationSettings: "'FILL' 1" }}
            aria-label={statusIcon.ariaLabel}
          >
            {statusIcon.icon}
          </span>
          <div className="text-left">
            <div className="text-[10px] font-headline uppercase tracking-widest opacity-60">
              Tool Executed
            </div>
            <div className="text-[12px] font-mono text-primary font-bold">
              {toolCall.name}
            </div>
          </div>
        </div>
        <span className="material-symbols-outlined text-on-surface-variant text-sm">
          {isExpanded ? "expand_less" : "code"}
        </span>
      </button>

      {isExpanded && (
        <div className="border-t border-white/5 p-4 space-y-3">
          {hasArguments && (
            <div className="space-y-1">
              <p className="text-[10px] font-headline uppercase tracking-widest text-on-surface-variant">
                Arguments
              </p>
              <pre className="max-h-48 overflow-auto rounded-lg bg-surface-container-lowest/50 p-3 text-xs font-mono text-on-surface-variant leading-relaxed">
                {formatArguments(toolCall.arguments)}
              </pre>
            </div>
          )}

          {toolCall.status === "success" && toolCall.result != null && (
            <div className="space-y-1">
              <p className="text-[10px] font-headline uppercase tracking-widest text-secondary">
                Result
              </p>
              <p className="whitespace-pre-wrap text-xs leading-relaxed text-on-surface">
                {toolCall.result}
              </p>
            </div>
          )}

          {toolCall.status === "error" && toolCall.error != null && (
            <div className="space-y-1">
              <p className="text-[10px] font-headline uppercase tracking-widest text-error">
                Error
              </p>
              <p className="whitespace-pre-wrap text-xs leading-relaxed text-error">
                {toolCall.error}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
