"use client";

import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/lib/stores/chat";
import { ThinkingSection } from "./thinking-section";

export interface AssistantMessageProps {
  message: ChatMessage;
  isStreaming?: boolean;
  tokenUsage?: TokenUsage | null;
  className?: string;
  /** Fork-from-here. When provided, a hover-revealed
   *  "Fork from here" button renders on assistant messages whose
   *  message.mcpId is set (i.e. messages loaded from MCP persistence,
   *  not live-streaming ones). Click invokes onFork(mcpId) so the
   *  chat page can POST to /api/agent/sessions/{id}/fork with
   *  {from_message_id}. */
  onFork?: (mcpMessageId: string) => void;
}

export interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
}

export function AssistantMessage({
  message,
  isStreaming = false,
  className,
  onFork,
}: AssistantMessageProps) {
  const text = message.text ?? "";
  const hasText = text.length > 0;
  const canFork = Boolean(onFork && message.mcpId && !isStreaming);

  return (
    <div className={cn("group flex justify-start items-start gap-4", className)}>
      <div className="w-10 h-10 rounded-full bg-gradient-to-br from-[#1963B3] to-[#2D8DF0] flex items-center justify-center shrink-0">
        <span
          className="material-symbols-outlined text-on-primary text-xl"
          style={{ fontVariationSettings: "'FILL' 1" }}
        >
          bolt
        </span>
      </div>
      <div className="max-w-[80%] space-y-4 relative">
        <ThinkingSection reasoning={message.reasoning} />
        {(hasText || isStreaming) && (
          <div className="glass-panel p-6 rounded-2xl rounded-tl-none border border-white/10 relative">
            <p className="text-sm leading-relaxed whitespace-pre-wrap">
              {hasText ? text : null}
              {isStreaming && (
                <span
                  className="inline-block w-2 h-4 bg-primary align-middle ml-1 animate-[blink_1s_step-end_infinite]"
                  aria-label="Typing"
                />
              )}
            </p>
            {canFork && (
              <button
                type="button"
                onClick={() => onFork!(message.mcpId!)}
                className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] text-on-surface-variant hover:text-on-surface bg-surface-container-low/60 hover:bg-surface-container-low border border-white/10"
                title="Fork a new session from this point. The new session inherits the conversation up to (and including) this message; further messages stay in the original."
                aria-label="Fork session from this message"
              >
                <span className="material-symbols-outlined text-[12px]">
                  call_split
                </span>
                Fork from here
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
