"use client";

import { useCallback, useRef, useState, type KeyboardEvent } from "react";
import { cn } from "@/lib/utils";

interface ChatInputProps {
  onSend: (text: string) => void;
  isStreaming: boolean;
  /**
   * Most-recent context-window utilization
   * as a 0..1 ratio (from chat handler's context_warning
   * event). When >= 0.8, the input renders a dismissible banner
   * suggesting `/compress` so the operator can pre-empt the
   * auto-compaction. Undefined = no warning observed yet.
   */
  contextUtilization?: number;
}

// ─── Toolbar Button ──────────────────────────────────────────────────────────

interface ToolbarButtonProps {
  icon: string;
  label: string;
  disabled?: boolean;
}

function ToolbarButton({ icon, label, disabled = true }: ToolbarButtonProps) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      title={disabled ? `${label} (coming soon)` : label}
      className="p-1.5 rounded-md text-on-surface-variant/50 hover:text-on-surface-variant hover:bg-white/5 transition-colors disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-on-surface-variant/50"
    >
      <span className="material-symbols-outlined text-base">{icon}</span>
    </button>
  );
}

// ─── Chat Input ──────────────────────────────────────────────────────────────

export function ChatInput({ onSend, isStreaming, contextUtilization }: ChatInputProps) {
  const [value, setValue] = useState("");
  const [isFocused, setIsFocused] = useState(false);
  const [bannerDismissed, setBannerDismissed] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Surface the /compress auto-suggest when
  // the chat is approaching its context window. We use 0.8 as the
  // soft threshold: the chat-route's context-window guard fires
  // `context_warning` at ~0.9, so 0.8 gives the operator a turn or
  // two of warning before auto-compaction kicks in. The banner is
  // dismissible per-render-cycle (it returns once the next warning
  // event lands at higher utilization).
  const showCompressBanner =
    typeof contextUtilization === "number" &&
    contextUtilization >= 0.8 &&
    !bannerDismissed;

  /** Insert text at the textarea cursor (or replace selection).
   *  Used by the /compress toolbar button so clicking it primes
   *  the textarea instead of sending immediately — operator still
   *  hits Enter to commit. */
  const insertText = useCallback((insert: string) => {
    setValue((prev) => {
      const el = textareaRef.current;
      if (!el) return prev + insert;
      const start = el.selectionStart ?? prev.length;
      const end = el.selectionEnd ?? prev.length;
      const next = prev.slice(0, start) + insert + prev.slice(end);
      // Defer cursor positioning until after React reconciles.
      requestAnimationFrame(() => {
        el.focus();
        const cursor = start + insert.length;
        el.setSelectionRange(cursor, cursor);
        el.style.height = "auto";
        el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
      });
      return next;
    });
  }, []);

  const resetHeight = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, []);

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || isStreaming) return;
    onSend(trimmed);
    setValue("");
    // Reset textarea height after clearing.
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (el) {
        el.style.height = "auto";
      }
    });
  }, [value, isStreaming, onSend]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  const canSend = !isStreaming && value.trim().length > 0;

  return (
    <div className="px-6 py-4 border-t border-white/5">
      {/* Context-window warning banner. Lives
          ABOVE the input container so it doesn't reflow the textarea
          height when it appears. The context-window guard fires the underlying
          context_warning event at ~90% utilization; we trigger at 80%
          so the operator has a turn or two of lead time before
          auto-compaction kicks in. Click "/compress" to insert the
          slash-command into the textarea (operator still hits Enter to
          commit, so this is suggestive not destructive). */}
      {showCompressBanner && (
        <div
          className="mb-2 px-3 py-2 rounded-lg flex items-center gap-2 text-[11px]"
          style={{
            background: "rgba(180, 83, 9, 0.10)",
            border: "0.5px solid rgba(180, 83, 9, 0.25)",
          }}
          role="status"
        >
          <span
            className="material-symbols-outlined text-tertiary text-base"
            aria-hidden="true"
          >
            warning
          </span>
          <span className="text-on-surface flex-1 leading-tight">
            Context is{" "}
            <span className="font-mono">
              {Math.round((contextUtilization ?? 0) * 100)}%
            </span>{" "}
            full. Run{" "}
            <button
              type="button"
              onClick={() => insertText("/compress")}
              className="font-mono px-1.5 py-0.5 rounded bg-tertiary/15 text-tertiary hover:bg-tertiary/25 transition-colors"
            >
              /compress
            </button>{" "}
            to summarize prior turns and free up budget.
          </span>
          <button
            type="button"
            onClick={() => setBannerDismissed(true)}
            aria-label="Dismiss compaction suggestion"
            className="p-0.5 rounded hover:bg-white/5 text-on-surface-variant/70 hover:text-on-surface transition-colors"
          >
            <span
              className="material-symbols-outlined text-sm"
              aria-hidden="true"
            >
              close
            </span>
          </button>
        </div>
      )}

      {/* Input container with conditional glow */}
      <div
        className={cn(
          "rounded-2xl transition-shadow duration-300",
          isFocused && "shadow-[0_0_20px_rgba(25,99,179,0.15)]",
        )}
        style={{
          background: "var(--glass-bg-strong)",
          backdropFilter: "blur(12px)",
          border: isFocused
            ? "0.5px solid rgba(25, 99, 179, 0.4)"
            : "0.5px solid var(--glass-border)",
        }}
      >
        {/* Toolbar row */}
        <div className="flex items-center gap-0.5 px-3 pt-2 pb-0">
          <ToolbarButton icon="attach_file" label="Attach file" />
          <ToolbarButton icon="image" label="Attach image" />
          <ToolbarButton icon="mic" label="Voice input" />
          {/* /compress quick-action. Inserts
              the slash command into the textarea instead of sending
              outright (operator commits with Enter). The "code" button
              was a coming-soon stub; replacing it with a real action
              keeps the toolbar visually balanced without a layout shift. */}
          <button
            type="button"
            aria-label="Insert /compress slash command"
            onClick={() => insertText("/compress")}
            disabled={isStreaming}
            title="Compact prior turns into a checkpoint to free up context budget"
            className="p-1.5 rounded-md text-on-surface-variant/70 hover:text-on-surface hover:bg-white/5 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <span className="material-symbols-outlined text-base">compress</span>
          </button>
        </div>

        {/* Textarea + Send */}
        <div className="flex items-end gap-3 px-4 py-3">
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              resetHeight();
            }}
            onKeyDown={handleKeyDown}
            onFocus={() => setIsFocused(true)}
            onBlur={() => setIsFocused(false)}
            // Placeholder hints at slash command
            // discoverability without bloating the empty-state UX. The
            // operator who types `/` first gets the recognition reward
            // ("oh, there's a /help"); the operator who never types
            // slash keeps the same prose-first experience.
            placeholder="Type your message — or /help for slash commands"
            disabled={isStreaming}
            rows={1}
            className="flex-1 resize-none bg-transparent text-on-surface placeholder:text-outline text-sm font-body leading-relaxed outline-none disabled:opacity-40 max-h-[200px]"
            aria-label="Chat message input"
          />
          <button
            onClick={handleSend}
            disabled={!canSend}
            aria-label="Send message"
            className="shrink-0 h-9 w-9 rounded-xl flex items-center justify-center text-on-surface transition-all disabled:opacity-30 disabled:cursor-not-allowed active:scale-95"
            style={{
              background: canSend
                ? "linear-gradient(135deg, #1963B3, #2D8DF0)"
                : "var(--glass-border)",
            }}
          >
            <span className="material-symbols-outlined text-lg">send</span>
          </button>
        </div>
      </div>

      {/* Hint + Disclaimer row */}
      <div className="flex items-center justify-between mt-2 px-1">
        <span className="text-[10px] text-outline font-label">
          <kbd className="px-1 py-0.5 rounded bg-white/5 text-[9px] font-mono">
            Shift
          </kbd>
          {" + "}
          <kbd className="px-1 py-0.5 rounded bg-white/5 text-[9px] font-mono">
            Enter
          </kbd>
          {" for new line"}
        </span>
        <span className="text-[10px] text-outline/60 font-label">
          Spark AI can make mistakes. Verify important information.
        </span>
      </div>
    </div>
  );
}
