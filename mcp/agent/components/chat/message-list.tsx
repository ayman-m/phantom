"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/lib/api/chat";
import { SparkLogo } from "@/components/sidebar";
import { MarkdownContent } from "@/components/markdown-content";
import { ThinkingSection } from "./thinking-section";
import type { SubagentActivity } from "./use-chat";

interface MessageListProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  isLoading?: boolean;
  /** Live subagent activity. Rendered as a
   *  sidechain card pinned below the latest assistant bubble. */
  subagents?: SubagentActivity[];
  /** Fork-from-here per assistant message. When provided,
   *  assistant bubbles whose `mcpId` is set (i.e. loaded from MCP
   *  persistence, not currently streaming) render a hover-revealed
   *  "Fork from here" button. Click invokes onForkFromMessage(mcpId);
   *  the chat page POSTs to /api/agent/sessions/{id}/fork with
   *  {from_message_id: mcpId}. */
  onForkFromMessage?: (mcpMessageId: string) => void;
}

/**
 * In-thread subagent activity card.
 *
 * Rendered below the latest assistant bubble for each subagent
 * the model spawned in this turn. Shows live tool-call progress
 * (pending / success / error per tool), blocked tools (scope
 * rejections), final response when completed.
 *
 * The subagent has its own session id; clicking the title opens
 * the persistent transcript so the operator can audit what the
 * subagent saw in full detail.
 */
function SubagentCard({ activity }: { activity: SubagentActivity }) {
  const [expanded, setExpanded] = useState(activity.status === "running");
  const tone =
    activity.status === "running"
      ? { bg: "bg-primary/10", fg: "text-primary", icon: "play_circle" }
      : activity.status === "completed"
        ? {
            bg: "bg-secondary/10",
            fg: "text-secondary",
            icon: "check_circle",
          }
        : activity.status === "denied"
          ? {
              bg: "bg-tertiary/10",
              fg: "text-tertiary",
              icon: "block",
            }
          : { bg: "bg-error/10", fg: "text-error", icon: "error" };

  return (
    <div className="my-2 max-w-[85%] mx-auto">
      <div
        className={cn("rounded-2xl px-4 py-3 space-y-2", tone.bg)}
        style={{ border: "0.5px solid var(--glass-border)" }}
      >
        {/* Header */}
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex items-center gap-2 w-full text-left"
          aria-expanded={expanded}
        >
          <span
            className={cn(
              "material-symbols-outlined text-base",
              tone.fg,
              activity.status === "running" && "animate-pulse",
            )}
            aria-hidden="true"
          >
            {tone.icon}
          </span>
          <span className="font-mono text-xs font-semibold text-on-surface flex-1 truncate">
            subagent: {activity.agent_name}
          </span>
          <span
            className={cn(
              "text-[10px] font-mono px-1.5 py-0.5 rounded uppercase tracking-wider",
              tone.bg,
              tone.fg,
            )}
          >
            {activity.status}
          </span>
          {activity.duration_ms != null && (
            <span className="text-[10px] font-mono text-on-surface-variant/60">
              {Math.round(activity.duration_ms / 100) / 10}s
            </span>
          )}
          <span
            className="material-symbols-outlined text-sm text-on-surface-variant/60"
            aria-hidden="true"
          >
            {expanded ? "expand_less" : "expand_more"}
          </span>
        </button>

        {expanded && (
          <div className="pt-1 space-y-2 text-[11px]">
            <p className="text-on-surface-variant italic">
              <span className="font-label uppercase tracking-wider text-[9px] mr-1.5 text-on-surface-variant/60">
                prompt:
              </span>
              {activity.prompt}
            </p>

            {/* Tool-call timeline */}
            {activity.tool_calls.length > 0 && (
              <ol className="space-y-1">
                {activity.tool_calls.map((tc, i) => (
                  <li
                    key={i}
                    className="flex items-center gap-1.5 font-mono text-[11px]"
                  >
                    <span
                      className={cn(
                        "material-symbols-outlined text-[12px]",
                        tc.status === "pending"
                          ? "text-primary animate-spin"
                          : tc.status === "success"
                            ? "text-secondary"
                            : "text-error",
                      )}
                    >
                      {tc.status === "pending"
                        ? "hourglass_top"
                        : tc.status === "success"
                          ? "check"
                          : "error"}
                    </span>
                    <span className="text-on-surface-variant truncate">
                      {tc.tool}
                    </span>
                  </li>
                ))}
              </ol>
            )}

            {/* Blocked tools (scope rejections) */}
            {activity.blocked_tools.length > 0 && (
              <div className="rounded-md bg-error/10 px-2 py-1.5 space-y-0.5">
                <p className="text-[10px] font-label uppercase tracking-wider text-error">
                  Blocked by subagent scope:
                </p>
                {activity.blocked_tools.map((b, i) => (
                  <p
                    key={i}
                    className="font-mono text-[11px] text-error/90 break-all"
                  >
                    {b.tool}
                  </p>
                ))}
              </div>
            )}

            {/* Final response */}
            {activity.final_response && (
              <div className="rounded-md bg-surface-container-lowest/50 px-3 py-2 mt-2">
                <p className="text-[10px] font-label uppercase tracking-wider text-on-surface-variant/60 mb-1">
                  Subagent response
                </p>
                <p className="text-[12px] text-on-surface whitespace-pre-wrap leading-relaxed">
                  {activity.final_response}
                </p>
              </div>
            )}

            {activity.error && (
              <div className="rounded-md bg-error/10 px-2 py-1.5">
                <p className="text-[10px] font-label uppercase tracking-wider text-error mb-0.5">
                  Error
                </p>
                <p className="font-mono text-[11px] text-error/90 break-all">
                  {activity.error}
                </p>
              </div>
            )}

            {/* Sidechain link */}
            {activity.subagent_session_id && (
              <p className="text-[10px] font-mono text-on-surface-variant/60 pt-1">
                Sidechain transcript:{" "}
                <a
                  href={`/?session=${activity.subagent_session_id}`}
                  className="text-primary hover:underline"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  session {activity.subagent_session_id.slice(0, 8)}…
                </a>
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * In-thread plan card.
 *
 * Renders the markdown plan emitted by /plan in a distinct visual
 * container. The body is collapsible — long plans (10+ steps) get
 * dense quickly, and the operator usually wants to skim the first
 * couple steps then scroll past while continuing the conversation.
 *
 * Displays the source prompt as a header so the operator can
 * remember what triggered this plan ("oh right, I asked it to plan
 * a 4h FortiGate scenario").
 */
function PlanCard({ message }: { message: ChatMessage }) {
  const [collapsed, setCollapsed] = useState(false);
  const meta = message.meta ?? {};
  const sourcePrompt =
    typeof meta["source_prompt"] === "string" ? meta["source_prompt"] : null;

  return (
    <div className="my-2 max-w-[85%] mx-auto">
      <div
        className="rounded-2xl px-5 py-4 space-y-2"
        style={{
          background: "var(--m3-tertiary-container)",
          opacity: 0.95,
          border: "0.5px solid var(--m3-tertiary)",
        }}
      >
        <div className="flex items-center gap-2">
          <span
            className="material-symbols-outlined text-base text-tertiary"
            aria-hidden="true"
          >
            map
          </span>
          <span className="font-label text-[10px] uppercase tracking-widest text-on-tertiary-container/80">
            Proposed plan
          </span>
          {sourcePrompt && (
            <span
              className="text-[11px] text-on-tertiary-container/70 italic truncate flex-1"
              title={sourcePrompt}
            >
              for: {sourcePrompt}
            </span>
          )}
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            aria-label={collapsed ? "Expand plan" : "Collapse plan"}
            className="p-1 rounded hover:bg-white/5 text-on-tertiary-container/70 hover:text-on-tertiary-container"
          >
            <span
              className="material-symbols-outlined text-sm"
              aria-hidden="true"
            >
              {collapsed ? "expand_more" : "expand_less"}
            </span>
          </button>
        </div>
        {!collapsed && (
          <div className="text-sm text-on-tertiary-container whitespace-pre-wrap leading-relaxed">
            {message.content}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * In-thread compaction marker.
 *
 * Renders the "─── compacted N messages ───" divider that signals
 * "everything before this row got rolled into a checkpoint summary."
 * Click expands the summary text inline, so the operator can read
 * what was preserved without leaving the chat thread.
 *
 * Same component handles BOTH manual /compress and
 * auto-compaction — the meta.compaction_kind discriminator just
 * tweaks the icon + label so the operator can tell them apart.
 */
function CompactionDivider({ message }: { message: ChatMessage }) {
  const [expanded, setExpanded] = useState(false);
  const meta = message.meta ?? {};
  const messagesSummarized = Number(meta["messages_summarized"]) || 0;
  const summaryChars = meta["summary_chars"] != null
    ? Number(meta["summary_chars"])
    : null;
  const kind = meta["compaction_kind"] === "auto" ? "auto" : "manual";
  const hasContent = Boolean(message.content && message.content.trim().length > 0);

  const label =
    kind === "auto"
      ? `Auto-compacted ${messagesSummarized} ${
          messagesSummarized === 1 ? "message" : "messages"
        } at the budget edge`
      : `Compacted ${messagesSummarized} prior ${
          messagesSummarized === 1 ? "message" : "messages"
        }`;

  return (
    <div className="my-2 flex flex-col items-center gap-2">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        disabled={!hasContent}
        className="flex items-center gap-2 px-3 py-1 rounded-full text-[11px] text-on-surface-variant/80 hover:text-on-surface transition-colors disabled:cursor-default disabled:hover:text-on-surface-variant/80"
        aria-label={`${label}${hasContent ? " — click to expand" : ""}`}
        aria-expanded={expanded}
      >
        {/* Left rule */}
        <span
          aria-hidden="true"
          className="block w-12 h-px"
          style={{
            background:
              "linear-gradient(to right, transparent, var(--m3-outline, rgba(255,255,255,0.2)))",
          }}
        />
        <span
          className="material-symbols-outlined text-[14px]"
          style={{
            color: kind === "auto" ? "var(--m3-tertiary)" : "var(--m3-primary)",
          }}
          aria-hidden="true"
        >
          {kind === "auto" ? "auto_awesome_motion" : "compress"}
        </span>
        <span className="font-label uppercase tracking-wider">{label}</span>
        {summaryChars != null && (
          <span className="font-mono text-[10px] text-outline">
            ~{summaryChars.toLocaleString()} char summary
          </span>
        )}
        {hasContent && (
          <span
            className="material-symbols-outlined text-[14px] text-on-surface-variant/50"
            aria-hidden="true"
          >
            {expanded ? "expand_less" : "expand_more"}
          </span>
        )}
        {/* Right rule */}
        <span
          aria-hidden="true"
          className="block w-12 h-px"
          style={{
            background:
              "linear-gradient(to left, transparent, var(--m3-outline, rgba(255,255,255,0.2)))",
          }}
        />
      </button>
      {expanded && hasContent && (
        <div
          className="max-w-[80%] rounded-2xl px-5 py-4 text-[12px] leading-relaxed text-on-surface-variant whitespace-pre-wrap"
          style={{
            background: "var(--glass-bg-strong)",
            backdropFilter: "blur(12px)",
            border: "0.5px solid var(--glass-border)",
          }}
        >
          <div className="flex items-center gap-2 mb-2 text-[10px] font-label uppercase tracking-wider text-on-surface-variant/60">
            <span
              className="material-symbols-outlined text-[12px]"
              aria-hidden="true"
            >
              article
            </span>
            Checkpoint summary
          </div>
          {message.content}
        </div>
      )}
    </div>
  );
}

const glassStyle = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

function formatMessageTime(timestamp: string): string {
  const date = new Date(timestamp);
  return date.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}

export function MessageList({
  messages,
  isStreaming,
  isLoading = false,
  subagents = [],
  onForkFromMessage,
}: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, subagents]);

  if (isLoading) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-5 text-on-surface-variant">
        <div
          className="rounded-2xl px-8 py-7 flex flex-col items-center gap-4"
          style={glassStyle}
        >
          {/* Animated icon */}
          <div
            className="w-12 h-12 rounded-xl flex items-center justify-center"
            style={{
              background:
                "linear-gradient(135deg, rgba(25, 99, 179, 0.25), rgba(45, 141, 240, 0.12))",
              border: "0.5px solid rgba(25, 99, 179, 0.2)",
            }}
          >
            <span
              className="material-symbols-outlined text-2xl text-primary animate-pulse"
              style={{ fontVariationSettings: "'FILL' 1" }}
            >
              history
            </span>
          </div>

          {/* Label */}
          <p className="text-sm font-headline font-medium text-on-surface">
            Loading conversation...
          </p>

          {/* Progress bar */}
          <div
            className="w-48 h-1.5 rounded-full overflow-hidden"
            style={{ background: "rgba(167, 200, 255, 0.1)" }}
          >
            <div
              className="h-full rounded-full animate-[progress_1.4s_ease-in-out_infinite]"
              style={{
                background:
                  "linear-gradient(90deg, #a7c8ff, #2D8DF0, #a7c8ff)",
                backgroundSize: "200% 100%",
              }}
            />
          </div>
        </div>

        {/* Inline keyframes for the progress animation */}
        <style>{`
          @keyframes progress {
            0% { transform: translateX(-100%); }
            100% { transform: translateX(200%); }
          }
        `}</style>
      </div>
    );
  }

  if (messages.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-4 text-on-surface-variant">
        <div className="w-16 h-16 rounded-2xl flex items-center justify-center">
          <SparkLogo size={48} />
        </div>
        <div className="text-center">
          <p className="text-sm font-headline font-medium text-on-surface">
            Start a conversation
          </p>
          <p className="text-xs text-on-surface-variant/60 mt-1 font-label">
            Ask anything or pick up where you left off
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto px-6 py-6 space-y-5 custom-scrollbar">
      {messages.map((msg, idx) => {
        // System rows with
        // meta.kind=compaction-checkpoint render as a horizontal
        // divider, NOT a chat bubble. Other system rows are
        // pre-filtered out (see getSessionTranscript), but we guard
        // here too so a future system kind doesn't accidentally
        // render as a blank bubble.
        if (msg.role === "system") {
          if (msg.meta?.["kind"] === "compaction-checkpoint") {
            return (
              <CompactionDivider
                key={`system-${idx}-${msg.timestamp}`}
                message={msg}
              />
            );
          }
          // Plan-proposed renders as a
          // distinct card.
          if (msg.meta?.["kind"] === "plan-proposed") {
            return (
              <PlanCard
                key={`system-${idx}-${msg.timestamp}`}
                message={msg}
              />
            );
          }
          return null;
        }

        const isUser = msg.role === "user";
        const isLastAssistant =
          !isUser && idx === messages.length - 1 && isStreaming;
        const showPulse = isLastAssistant && msg.content === "";

        // ^-prefix direct tool commands render in
        // a distinct visual style — a monospace pill for the user side,
        // a JSON code block for the result. Visually different from
        // chat bubbles so operators see at a glance "this was a direct
        // tool call, not an LLM turn." The result is the raw tool
        // output (parsed JSON); errors render in error-tinted styling.
        const metaKind = msg.meta?.["kind"];
        if (metaKind === "tool_command") {
          return (
            <div key={`${msg.role}-${idx}`} className="flex justify-end gap-3">
              <div className="max-w-[70%]">
                <div
                  className="rounded-xl px-3.5 py-2 text-xs font-mono leading-relaxed text-on-surface"
                  style={{
                    background: "rgba(167, 200, 255, 0.1)",
                    border: "0.5px solid rgba(167, 200, 255, 0.25)",
                  }}
                >
                  <span className="text-primary mr-1">▸</span>
                  <span className="whitespace-pre-wrap break-words">{msg.content}</span>
                </div>
                <div className="flex justify-end mt-1 px-1">
                  <span className="text-[10px] text-outline/60 font-label">
                    direct tool call · {formatMessageTime(msg.timestamp)}
                  </span>
                </div>
              </div>
              <div className="shrink-0 w-8 h-8 rounded-lg flex items-center justify-center bg-primary-container/20">
                <span className="material-symbols-outlined text-sm text-primary">
                  terminal
                </span>
              </div>
            </div>
          );
        }
        if (metaKind === "tool_command_result") {
          const status = msg.meta?.["status"];
          const isErr = status === "error";
          const isPending = status === "pending";
          const resolvedName = msg.meta?.["resolved_name"];
          const durationMs = msg.meta?.["duration_ms"];
          return (
            <div key={`${msg.role}-${idx}`} className="flex items-start gap-3">
              <div className="shrink-0 w-8 h-8 rounded-lg flex items-center justify-center">
                <span
                  className={`material-symbols-outlined text-base ${
                    isErr
                      ? "text-error"
                      : isPending
                        ? "text-on-surface-variant animate-spin"
                        : "text-primary"
                  }`}
                >
                  {isErr ? "error" : isPending ? "progress_activity" : "data_object"}
                </span>
              </div>
              <div className="max-w-[75%] flex-1 min-w-0">
                <div
                  className="rounded-xl overflow-hidden"
                  style={{
                    background: isErr
                      ? "rgba(186, 26, 26, 0.08)"
                      : "rgba(20, 22, 32, 0.6)",
                    border: isErr
                      ? "0.5px solid rgba(186, 26, 26, 0.25)"
                      : "0.5px solid rgba(255, 255, 255, 0.06)",
                  }}
                >
                  {(Boolean(resolvedName) || Boolean(durationMs)) && (
                    <div
                      className="px-3 py-1.5 text-[10px] font-label uppercase tracking-wider text-on-surface-variant border-b flex items-center gap-2"
                      style={{ borderColor: "rgba(255, 255, 255, 0.05)" }}
                    >
                      {resolvedName ? (
                        <span className="text-primary/80">{String(resolvedName)}</span>
                      ) : null}
                      {durationMs ? (
                        <span className="ml-auto">{String(durationMs)} ms</span>
                      ) : null}
                    </div>
                  )}
                  <pre className="px-3 py-2.5 text-xs font-mono leading-relaxed text-on-surface whitespace-pre-wrap break-words overflow-x-auto custom-scrollbar">
                    {isPending ? "running…" : msg.content || "{}"}
                  </pre>
                </div>
                <div className="flex mt-1 px-1">
                  <span className="text-[10px] text-outline/60 font-label">
                    {formatMessageTime(msg.timestamp)}
                  </span>
                </div>
              </div>
            </div>
          );
        }

        if (isUser) {
          return (
            <div key={`${msg.role}-${idx}`} className="flex justify-end gap-3">
              <div className="max-w-[70%]">
                <div
                  className="rounded-2xl rounded-tr-none px-5 py-3.5 text-sm leading-relaxed text-on-surface"
                  style={{
                    background: "rgba(25, 99, 179, 0.2)",
                    border: "0.5px solid rgba(25, 99, 179, 0.15)",
                  }}
                >
                  <span className="whitespace-pre-wrap break-words">
                    {msg.content}
                  </span>
                </div>
                <div className="flex justify-end mt-1 px-1">
                  <span className="text-[10px] text-outline/60 font-label">
                    {formatMessageTime(msg.timestamp)}
                  </span>
                </div>
              </div>
              {/* User avatar */}
              <div className="shrink-0 w-8 h-8 rounded-lg flex items-center justify-center bg-primary-container/20">
                <span className="material-symbols-outlined text-sm text-primary">
                  person
                </span>
              </div>
            </div>
          );
        }

        // Assistant message
        // Per-message Fork-from-here. Only enabled when the
        // message has an mcpId (loaded from MCP persistence; new
        // streamed messages don't have one until session reload) AND
        // it's not currently streaming. Hidden by default; revealed on
        // group hover via the `group/asst-msg` + `group-hover` pair.
        const canForkFromHere =
          Boolean(onForkFromMessage) &&
          Boolean(msg.mcpId) &&
          !isLastAssistant;
        return (
          <div
            key={`${msg.role}-${idx}`}
            className="group/asst-msg flex items-start gap-3"
          >
            {/* Bot avatar */}
            <div className="shrink-0 w-8 h-8 rounded-lg flex items-center justify-center">
              <SparkLogo size={28} animate={false} />
            </div>

            <div className="max-w-[75%]">
              {/* Reasoning section. Rendered when msg.reasoning
                  is non-empty (model engaged extended thinking and route
                  emitted `thinking` SSE events). Collapsed-by-default so
                  the operator skims the answer first; expanding shows
                  the model's monologue. Renders nothing when there's no
                  reasoning, so non-thinking turns visually unchanged. */}
              <ThinkingSection reasoning={msg.reasoning} className="mb-2" />
              <div
                className="rounded-2xl rounded-tl-none px-5 py-3.5 text-sm leading-relaxed text-on-surface relative"
                style={glassStyle}
              >
                {showPulse ? (
                  <span className="inline-flex gap-1.5 items-center py-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                    <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse [animation-delay:150ms]" />
                    <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse [animation-delay:300ms]" />
                  </span>
                ) : (
                  // Narrative / answer split rendering. If
                  // boundaryIndices is present, the text BEFORE the
                  // last boundary is the agent's tool-call narration
                  // ("I'll call X next...", "now let me check Y...")
                  // and renders in a muted style; the text AFTER is
                  // the final answer and renders prominently. If no
                  // boundaries (no tool calls fired, or message
                  // loaded from MCP storage where the field is
                  // dropped), the entire content renders as one
                  // block. The blinking cursor only attaches to the
                  // last (answer or single-block) span so the typing
                  // indicator doesn't ambiguously land mid-bubble.
                  (() => {
                    const boundaries = msg.boundaryIndices ?? [];
                    const lastBoundary = boundaries.length > 0
                      ? boundaries[boundaries.length - 1]
                      : null;
                    const narrative = lastBoundary != null
                      ? msg.content.slice(0, lastBoundary)
                      : "";
                    const answer = lastBoundary != null
                      ? msg.content.slice(lastBoundary)
                      : msg.content;
                    const cursor = isLastAssistant && (
                      <span
                        className="inline-block w-2 h-4 bg-primary align-middle ml-1 animate-[blink_1s_step-end_infinite]"
                        aria-label="Typing"
                      />
                    );
                    return (
                      <>
                        {narrative && (
                          <div
                            className="mb-3 px-3 py-2 rounded-md border border-white/5 bg-white/3 text-on-surface-variant text-xs italic whitespace-pre-wrap break-words flex gap-2"
                            title="Agent narration — tool-call announcements and reasoning. The final answer is below."
                          >
                            <span
                              className="material-symbols-outlined text-[14px] shrink-0 mt-0.5 text-outline/60"
                              aria-hidden="true"
                            >
                              auto_awesome
                            </span>
                            <span className="flex-1">{narrative}</span>
                          </div>
                        )}
                        {/* The answer portion of an
                            assistant message renders through the
                            shared MarkdownContent renderer so model-
                            returned markdown (headings, code blocks
                            with SQL/XQL syntax highlighting, lists,
                            tables, etc.) shows up styled instead of
                            raw `whitespace-pre-wrap` text. The
                            blinking cursor still trails the answer
                            during streaming.

                            While streaming, the answer is partial —
                            could be mid-fence (```sql / no closing
                            ```). ReactMarkdown handles partial
                            markdown gracefully; mid-fence fences
                            render as plain text until the closing
                            ``` arrives. */}
                        <div className="break-words">
                          <MarkdownContent compact>{answer}</MarkdownContent>
                          {cursor}
                        </div>
                      </>
                    );
                  })()
                )}
                {canForkFromHere && (
                  <button
                    type="button"
                    onClick={() => onForkFromMessage!(msg.mcpId!)}
                    className="absolute top-2 right-2 opacity-0 group-hover/asst-msg:opacity-100 focus:opacity-100 transition-opacity inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] text-on-surface-variant hover:text-on-surface bg-surface-container-low/80 hover:bg-surface-container-low border border-white/10"
                    title="Fork a new session from this point. Conversation up to (and including) this message is copied; further messages stay in the original."
                    aria-label="Fork session from this message"
                  >
                    <span className="material-symbols-outlined text-[12px]">
                      call_split
                    </span>
                    Fork from here
                  </button>
                )}
              </div>

              {/* Footer: timestamp + token usage */}
              <div className="flex items-center gap-3 mt-1 px-1">
                <span className="text-[10px] text-outline/60 font-label">
                  {formatMessageTime(msg.timestamp)}
                </span>
                {/* Token usage badge (shown for completed assistant messages) */}
                {!isLastAssistant && msg.content.length > 0 && (
                  <span className="text-[10px] text-outline/40 font-label flex items-center gap-1">
                    <span className="material-symbols-outlined text-[10px]">
                      token
                    </span>
                    ~{Math.ceil(msg.content.length / 4)} tokens
                  </span>
                )}
              </div>
            </div>
          </div>
        );
      })}
      {/* Subagent activity cards. Pinned at
          the bottom of the thread, below the latest assistant
          bubble, so the live tool-call timeline stays visible
          while the model continues reasoning. */}
      {subagents.map((s) => (
        <SubagentCard key={s.subagent_session_id} activity={s} />
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
