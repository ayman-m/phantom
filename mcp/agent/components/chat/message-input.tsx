"use client";

import { useCallback, useRef, useState } from "react";
import { cn } from "@/lib/utils";

export interface MessageInputProps {
  onSend: (text: string) => void;
  onAbort: () => void;
  isRunning: boolean;
  isSubmitting: boolean;
  models?: string[];
  selectedModel?: string;
  onModelChange?: (model: string) => void;
  placeholder?: string;
  className?: string;
}

const MAX_ROWS = 6;
const LINE_HEIGHT_PX = 24;
const PADDING_PX = 16;

export function MessageInput({
  onSend,
  onAbort,
  isRunning,
  isSubmitting,
  placeholder = "Send a message...",
  className,
}: MessageInputProps) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const adjustHeight = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    const maxHeight = LINE_HEIGHT_PX * MAX_ROWS + PADDING_PX;
    textarea.style.height = `${Math.min(textarea.scrollHeight, maxHeight)}px`;
  }, []);

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      setText(e.target.value);
      adjustHeight();
    },
    [adjustHeight],
  );

  const canSend = text.trim().length > 0 && !isRunning && !isSubmitting;

  const handleSend = useCallback(() => {
    if (!canSend) return;
    onSend(text.trim());
    setText("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [canSend, onSend, text]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  return (
    <div className={cn("absolute bottom-0 left-0 w-full p-8 bg-gradient-to-t from-surface to-transparent", className)}>
      <div className="glass-panel rounded-2xl p-2 flex flex-col shadow-2xl">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={isRunning || isSubmitting}
          rows={1}
          aria-label="Message input"
          className="w-full bg-transparent border-none focus:ring-0 text-sm p-4 h-24 resize-none placeholder:text-on-surface-variant/40 custom-scrollbar font-body outline-none disabled:cursor-not-allowed disabled:opacity-50"
        />
        <div className="flex items-center justify-between p-2 border-t border-white/5">
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="p-2 text-on-surface-variant hover:text-primary transition-colors"
              aria-label="Attach file"
            >
              <span className="material-symbols-outlined">attach_file</span>
            </button>
            <button
              type="button"
              className="p-2 text-on-surface-variant hover:text-primary transition-colors"
              aria-label="Language"
            >
              <span className="material-symbols-outlined">language</span>
            </button>
            <button
              type="button"
              className="p-2 text-on-surface-variant hover:text-primary transition-colors"
              aria-label="Image"
            >
              <span className="material-symbols-outlined">image</span>
            </button>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-[10px] text-on-surface-variant/60 font-headline uppercase tracking-widest hidden md:block">
              Enter to send · Shift+Enter for newline
            </span>
            {isSubmitting ? (
              <div
                aria-label="Sending message"
                className="w-10 h-10 rounded-xl bg-surface-container flex items-center justify-center"
              >
                <span className="material-symbols-outlined animate-spin text-on-surface-variant">
                  progress_activity
                </span>
              </div>
            ) : isRunning ? (
              <button
                type="button"
                aria-label="Abort run"
                onClick={onAbort}
                className="w-10 h-10 rounded-xl bg-error-container text-on-error-container flex items-center justify-center hover:bg-error transition-colors shadow-lg active:scale-95 duration-200"
              >
                <span
                  className="material-symbols-outlined"
                  style={{ fontVariationSettings: "'FILL' 1" }}
                >
                  stop
                </span>
              </button>
            ) : (
              <button
                type="button"
                aria-label="Send message"
                disabled={!canSend}
                onClick={handleSend}
                className="w-10 h-10 rounded-xl bg-gradient-to-r from-primary-container to-[#2D8DF0] text-on-primary-container flex items-center justify-center shadow-lg active:scale-95 duration-200 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <span
                  className="material-symbols-outlined"
                  style={{ fontVariationSettings: "'FILL' 1" }}
                >
                  send
                </span>
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
